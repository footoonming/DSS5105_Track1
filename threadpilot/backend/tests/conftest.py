"""场景 1.1–3.3：HTTP 测试通过 SQLAlchemy 使用隔离数据库。"""
from pathlib import Path
import pytest
from app.config import Settings
from app.db.session import Database
from app.db.base import Base
from app.models import SyncLock
from app.services.importer import import_bytes


@pytest.fixture(autouse=True)
def business_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """场景 1.2：保持原意图断言，将正式三表导入隔离数据库。"""
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + (tmp_path / 'business.sqlite3').as_posix())
    monkeypatch.setenv('AI_DATABASE_URL', '')
    monkeypatch.setenv('SYNC_ENABLED', 'false')
    monkeypatch.setenv('DATA_API_TOKEN', 'test-management-token')
    database = Database(Settings())
    Base.metadata.create_all(database.engine)
    with database.sessions.begin() as session:
        session.add(SyncLock(id=1))
    root = Path(__file__).resolve().parents[2]
    for name in ('orders', 'production_log', 'workshops'):
        path = root / 'data' / (name + '.csv')
        import_bytes(database, path.read_bytes(), path.name)
    yield database
    database.close()
