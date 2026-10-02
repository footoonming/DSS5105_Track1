"""场景 1.2：人工上传及同步审计接口。"""
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from .security import confirm_write, require_admin
from .data_api import DB
from ..models import SyncLog
from ..schemas_db.data_record import Dataset
from ..schemas_db.sync_log import SyncRead
from ..services.importer import import_bytes

router = APIRouter(prefix='/api/sync', tags=['Synchronization'])


@router.post('/import', response_model=SyncRead, dependencies=[Depends(confirm_write)])
def import_file(request: Request, file: UploadFile = File(...), dataset: Dataset | None = None) -> SyncRead:
    """场景 1.2：上传后原子导入，不覆盖原始文件，不接受服务器任意路径。"""
    content = file.file.read(request.app.state.settings.max_upload_bytes + 1)
    if len(content) > request.app.state.settings.max_upload_bytes:
        raise HTTPException(413, {'code': 'FILE_TOO_LARGE', 'message': 'Upload exceeds configured limit.'})
    return import_bytes(request.app.state.database, content, file.filename or 'source.xlsx', dataset)


@router.get('/logs', response_model=list[SyncRead], dependencies=[Depends(require_admin)])
def logs(session: DB) -> list[SyncRead]:
    """场景 1.2/2.2：管理员读取最近一百条同步审计。"""
    return [SyncRead.model_validate(r) for r in session.scalars(select(SyncLog).order_by(SyncLog.id.desc()).limit(100))]
