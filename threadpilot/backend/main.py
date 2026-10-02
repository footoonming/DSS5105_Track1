"""场景 1.1–3.3：保留 main:app 启动入口，统一使用工作流应用。"""
from app.main import app, create_app

__all__ = ['app', 'create_app']
