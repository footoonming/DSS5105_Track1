"""场景 1.2/3.2：统一键、版本和业务序列化规则。"""
import hashlib
import json
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models.data_record import Order, ProductionRecord, Workshop, DataRecord, SyncLock
from ..schemas_db.data_record import OrderFields, ProductionFields, WorkshopFields, RecordRead

MODELS = {'orders': Order, 'production_log': ProductionRecord, 'workshops': Workshop}
SCHEMAS = {'orders': OrderFields, 'production_log': ProductionFields, 'workshops': WorkshopFields}
KEYS = {'orders': ('order_id',), 'production_log': ('date', 'stage'), 'workshops': ('workshop_id',)}


def lock_writes(session: Session) -> None:
    """场景 1.2：API 和导入共用数据库行锁，跨进程防止覆盖。"""
    if session.scalar(select(SyncLock).where(SyncLock.id == 1).with_for_update()) is None:
        raise RuntimeError('Run Alembic migrations before writing')


def fields(dataset: str, record: DataRecord) -> dict[str, Any]:
    """场景 1.2：只提取业务字段，不将审计列当作源记录。"""
    return SCHEMAS[dataset].model_validate({name: getattr(record, name) for name in SCHEMAS[dataset].model_fields}).model_dump(mode='json')


def fingerprint(values: dict[str, Any]) -> str:
    """场景 1.2：规范化后计算行哈希，区分文件变动与 API 变动。"""
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def natural_key(dataset: str, values: dict[str, Any]) -> str:
    """场景 1.1/1.2：稳定业务键，不以 Excel 行号作为主键。"""
    return dataset + ':' + '|'.join(str(values[k]) for k in KEYS[dataset])


def read_record(dataset: str, record: DataRecord) -> RecordRead:
    """场景 1.2：返回当前版本和源证据定位。"""
    return RecordRead(id=record.id, dataset=dataset, data=fields(dataset, record), version=record.version,
                      source=record.source, source_row=record.source_row, created_at=record.created_at, updated_at=record.updated_at)
