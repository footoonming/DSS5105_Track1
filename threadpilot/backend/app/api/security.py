"""场景 3.1–3.3：管理写入与模型工具分离。"""
import secrets
from fastapi import Depends, Header, HTTPException, Request


def require_admin(request: Request, authorization: str = Header(default='')) -> None:
    """场景 3.2：数据管理调用必须携带独立管理令牌。"""
    token = request.app.state.settings.data_api_token.get_secret_value()
    if not token or not secrets.compare_digest(authorization, 'Bearer ' + token):
        raise HTTPException(401, {'code': 'UNAUTHORIZED', 'message': 'A configured DATA_API_TOKEN is required.'})


def confirm_write(x_confirm_write: str = Header(default=''), admin: None = Depends(require_admin)) -> None:
    """场景 3.2：身份验证后还需显式确认本次写入。"""
    if x_confirm_write.lower() != 'true':
        raise HTTPException(409, {'code': 'CONFIRMATION_REQUIRED', 'message': 'Review the write, then submit X-Confirm-Write: true.'})
