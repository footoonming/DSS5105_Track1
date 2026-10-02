"""场景 1.2/2.2：原子、幂等、冲突感知的表格增量导入。"""
import hashlib
from datetime import datetime
from zipfile import ZipFile, BadZipFile
from io import BytesIO
from pathlib import Path
from typing import Any
import pandas as pd
import yaml
from sqlalchemy import insert, select
from ..config import ROOT
from ..db.session import Database
from ..crud.data_record import MODELS, SCHEMAS, fields, fingerprint, natural_key, lock_writes
from ..models import SyncLog, Tombstone
from ..schemas_db.sync_log import SyncRead


class ImportConflict(ValueError):
    pass


def parse_file(content: bytes, filename: str, dataset: str | None = None) -> dict[str, list[tuple[int, dict[str, Any]]]]:
    """场景 1.2：清洗空值、类型、列映射；拒绝未知表和冲突重复键。"""
    mapping = yaml.safe_load((ROOT / 'data/dictionary/field_mapping.yaml').read_text(encoding='utf-8'))
    suffix = Path(filename).suffix.lower()
    if suffix == '.csv':
        name = dataset or Path(filename).stem
        frames = {name: pd.read_csv(BytesIO(content), dtype=object)}
    elif suffix == '.xlsx':
        with ZipFile(BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 100_000_000:
                raise ValueError('Expanded workbook exceeds 100 MB')
        frames = pd.read_excel(BytesIO(content), sheet_name=None, dtype=object, engine='openpyxl')
        if dataset and len(frames) == 1:
            frames = {dataset: next(iter(frames.values()))}
    else:
        raise ValueError('Only .csv and .xlsx files are supported')
    cleaned: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for name, frame in frames.items():
        if name not in MODELS:
            raise ValueError(f'Unknown dataset/sheet: {name}; use orders, production_log, workshops')
        frame.columns = [str(c).strip() for c in frame.columns]
        frame = frame.rename(columns=mapping.get(name, {}))
        if frame.columns.duplicated().any():
            raise ValueError(f'Duplicate mapped columns in {name}')
        allowed = set(SCHEMAS[name].model_fields)
        required = {key for key, field in SCHEMAS[name].model_fields.items() if field.is_required()}
        if set(frame.columns) - allowed or required - set(frame.columns):
            raise ValueError(f'Unknown or missing required columns in {name}; check the data dictionary')
        seen: dict[str, dict[str, Any]] = {}
        rows: list[tuple[int, dict[str, Any]]] = []
        for index, series in frame.iterrows():
            raw = {str(k): (None if pd.isna(v) or (isinstance(v, str) and not v.strip()) else v.strip() if isinstance(v, str) else v) for k, v in series.items()}
            if all(v is None for v in raw.values()):
                continue
            # Excel 日期单元格由 pandas 产生 Timestamp，显式转为日期。
            raw = {k: v.date().isoformat() if isinstance(v, (pd.Timestamp, datetime)) else v for k, v in raw.items()}
            validated = SCHEMAS[name].model_validate(raw).model_dump(mode='json')
            key = natural_key(name, validated)
            if key in seen:
                if seen[key] != validated:
                    raise ValueError(f'Conflicting duplicate key {key} at row {int(index) + 2}')
                continue
            seen[key] = validated
            rows.append((int(index) + 2, validated))
        cleaned[name] = rows
    return cleaned


def import_bytes(database: Database, content: bytes, filename: str, dataset: str | None = None) -> SyncRead:
    """场景 1.2：只更新真正变化的记录，不删除文件中缺失的行。"""
    source = Path(filename).name
    digest = hashlib.sha256(content).hexdigest()
    try:
        cleaned = parse_file(content, filename, dataset)
        with database.sessions.begin() as session:
            lock_writes(session)
            log = SyncLog(source=source, file_hash=digest, status='success', inserted=0, updated=0, skipped=0, message='')
            tombstones = set(session.scalars(select(Tombstone.key)))
            for name, rows in cleaned.items():
                model = MODELS[name]
                current = {natural_key(name, fields(name, r)): r for r in session.scalars(select(model))}
                additions: list[dict[str, Any]] = []
                for row_number, values in rows:
                    key, row_hash = natural_key(name, values), fingerprint(values)
                    record = current.get(key)
                    if key in tombstones:
                        log.skipped += 1
                        continue
                    if record is not None:
                        current_hash = fingerprint(fields(name, record))
                        if row_hash in (record.imported_hash, current_hash):
                            if row_hash == current_hash:
                                record.imported_hash = row_hash
                            log.skipped += 1
                            continue
                        if record.imported_hash is None or current_hash != record.imported_hash:
                            raise ImportConflict(f'{key}: API and file changes conflict; reconcile explicitly through CRUD')
                        for field, value in SCHEMAS[name].model_validate(values).model_dump().items():
                            setattr(record, field, value)
                        record.imported_hash, record.source, record.source_row = row_hash, source, row_number
                        record.version += 1
                        log.updated += 1
                    else:
                        additions.append({**SCHEMAS[name].model_validate(values).model_dump(), 'source': source,
                                          'source_row': row_number, 'imported_hash': row_hash, 'version': 1})
                        log.inserted += 1
                if additions:
                    session.execute(insert(model), additions)
            session.add(log)
            session.flush()
            result = SyncRead.model_validate(log)
        return result
    except Exception as error:
        # 失败审计单独提交；业务事务已全部回滚，不记录原始内容或连接字符串。
        with database.sessions.begin() as session:
            session.add(SyncLog(source=source, file_hash=digest, status='failed', message=type(error).__name__))
        if isinstance(error, (BadZipFile, pd.errors.EmptyDataError, pd.errors.ParserError)):
            raise ValueError('Invalid spreadsheet file structure') from error
        raise
