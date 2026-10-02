"""场景 1.2：前端启动时读取数据库快照。"""
from fastapi import APIRouter, Request, Response
from ..services.snapshot_service import snapshot
from ..workflow_api import business_now

router = APIRouter(tags=['Snapshot'])


@router.get('/api/snapshot')
def get_snapshot(request: Request, response: Response) -> dict:
    """场景 1.2：禁止浏览器缓存；每次请求都查询数据库。"""
    response.headers['Cache-Control'] = 'no-store'
    return snapshot(request.app.state.database, business_now().date().isoformat())
