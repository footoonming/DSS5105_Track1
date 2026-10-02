"""场景 1.2：每次请求使用独立 Session，不缓存业务数据。"""
from collections.abc import Iterator
from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from ..config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        """场景 1.2：延迟连接，允许 OpenAPI 离线生成。"""
        url = settings.database_url.get_secret_value()
        self.engine = make_engine(url)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def close(self) -> None:
        """场景 1.2：关闭连接池。"""
        self.engine.dispose()


def make_engine(url: str) -> Engine:
    """场景 1.2：MySQL 使用 READ COMMITTED，SQLite 仅用于隔离测试。"""
    if url.startswith('sqlite'):
        return create_engine(url, connect_args={'check_same_thread': False})
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, isolation_level='READ COMMITTED')


def get_session(request: Request) -> Iterator[Session]:
    """场景 1.2/3.2：依赖注入负责提交或回滚与释放。"""
    with request.app.state.database.sessions.begin() as session:
        yield session
