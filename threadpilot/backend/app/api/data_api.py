"""场景 1.2/3.2：标准 CRUD、稳定证据链接和乐观并发控制。"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..crud.data_record import MODELS, SCHEMAS, KEYS, fields, natural_key, read_record, lock_writes
from ..db.session import get_session
from ..models import Tombstone
from ..models.data_record import DataRecord
from ..schemas_db.data_record import Dataset, RecordWrite, RecordRead
from .security import confirm_write

router = APIRouter(tags=['Data'])
DB = Annotated[Session, Depends(get_session, scope='function')]


def find(session: Session, dataset: Dataset, record_id: int) -> DataRecord:
    """场景 1.1：按表名和稳定主键定位，不存在时明确返回 404。"""
    record = session.get(MODELS[dataset], record_id)
    if record is None:
        raise HTTPException(404, {'code': 'NOT_FOUND', 'message': 'Record not found.'})
    return record


@router.get('/api/data', response_model=list[RecordRead])
def list_records(session: DB, dataset: Dataset = 'orders', offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)) -> list[RecordRead]:
    """场景 1.2：有界分页读取最新提交的业务记录。"""
    model = MODELS[dataset]
    return [read_record(dataset, r) for r in session.scalars(select(model).order_by(model.id).offset(offset).limit(limit))]


@router.get('/api/data/{record_id}', response_model=RecordRead)
def get_record(record_id: int, session: DB, dataset: Dataset = 'orders') -> RecordRead:
    """场景 1.2：刷新单条记录。"""
    return read_record(dataset, find(session, dataset, record_id))


@router.get('/api/evidence/{dataset}/{record_id}')
def evidence(dataset: Dataset, record_id: int, session: DB) -> dict:
    """场景 1.3/2.2：展示查询时的当前记录、来源、时间和版本。"""
    result = read_record(dataset, find(session, dataset, record_id))
    return {**result.model_dump(mode="json"), "record": result.data}


@router.post('/api/data', response_model=RecordRead, status_code=201, dependencies=[Depends(confirm_write)])
def create_record(body: RecordWrite, session: DB) -> RecordRead:
    """场景 3.2：管理员确认后创建；主动重建可清除对应删除标记。"""
    values = SCHEMAS[body.dataset].model_validate(body.data)
    lock_writes(session)
    key = natural_key(body.dataset, values.model_dump(mode='json'))
    tombstone = session.get(Tombstone, key)
    if tombstone:
        session.delete(tombstone)
    record = MODELS[body.dataset](**values.model_dump(), source='api')
    session.add(record)
    session.flush()
    return read_record(body.dataset, record)


@router.put('/api/data/{record_id}', response_model=RecordRead, dependencies=[Depends(confirm_write)])
def update_record(record_id: int, body: RecordWrite, session: DB) -> RecordRead:
    """场景 1.2/3.2：PUT 完整替换业务字段，要求当前版本且不允许改业务主键。"""
    values = SCHEMAS[body.dataset].model_validate(body.data).model_dump()
    lock_writes(session)
    record = find(session, body.dataset, record_id)
    if body.expected_version != record.version:
        raise HTTPException(409, {'code': 'VERSION_CONFLICT', 'message': 'Read the latest record and supply expected_version.'})
    if any(values[k] != getattr(record, k) for k in KEYS[body.dataset]):
        raise HTTPException(422, {'code': 'IMMUTABLE_KEY', 'message': 'Business keys cannot be changed.'})
    for name, value in values.items():
        setattr(record, name, value)
    record.version += 1
    session.flush()
    return read_record(body.dataset, record)


@router.delete('/api/data/{record_id}', status_code=204, dependencies=[Depends(confirm_write)])
def delete_record(record_id: int, session: DB, expected_version: int = Query(ge=1), dataset: Dataset = 'orders') -> None:
    """场景 3.2：确认删除并记录墓碑，旧文件不会重新插入已删除记录。"""
    lock_writes(session)
    record = find(session, dataset, record_id)
    if expected_version != record.version:
        raise HTTPException(409, {'code': 'VERSION_CONFLICT', 'message': 'Read the latest version before deleting.'})
    session.merge(Tombstone(key=natural_key(dataset, fields(dataset, record))))
    session.delete(record)
