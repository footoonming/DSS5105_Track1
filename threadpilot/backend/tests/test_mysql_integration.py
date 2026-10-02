"""场景 1.1–3.3：仅对显式提供的专用 MySQL 测试库运行。"""
import os
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from app.config import ROOT, Settings
from app.db.session import Database, make_engine
from app.models import Order
from app.services.importer import import_bytes
from app.services.ai_sql_service import AISQLService


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        """场景 1.2：模拟模型选工具，实际 Agent 和 MySQL 执行路径不替换。"""
        return self


@pytest.mark.skipif(not os.getenv('TEST_MYSQL_URL'), reason='Set TEST_MYSQL_URL to an isolated test database')
def test_real_mysql_migrations_grants_and_agent(monkeypatch, tmp_path: Path) -> None:
    """场景 1.2：真实 MySQL 建表、幂等导入、只读权限及多轮刷新。"""
    url = os.environ['TEST_MYSQL_URL']
    if make_url(url).database != 'threadpilot_test':
        pytest.fail('TEST_MYSQL_URL must target the dedicated threadpilot_test database')
    monkeypatch.setenv('DATABASE_URL', url)
    config = Config(str(ROOT / 'backend/alembic.ini'))
    command.upgrade(config, 'head')
    command.check(config)
    database = Database(Settings(database_url=url))
    try:
        for name in ('orders', 'production_log', 'workshops'):
            path = ROOT / 'data' / (name + '.csv')
            result = import_bytes(database, path.read_bytes(), path.name)
            assert result.inserted + result.skipped == {'orders': 120, 'production_log': 360, 'workshops': 8}[name]
            assert import_bytes(database, path.read_bytes(), path.name).updated == 0
        # 账号只允许 SELECT 三张业务表；账号生命周期限定在专用测试实例。
        with database.engine.begin() as connection:
            connection.exec_driver_sql("CREATE USER IF NOT EXISTS 'tp_test_ai'@'localhost' IDENTIFIED BY 'only_for_isolated_tests_492'")
            for table in ('orders', 'production_log', 'workshops'):
                connection.exec_driver_sql(f"GRANT SELECT ON threadpilot_test.`{table}` TO 'tp_test_ai'@'localhost'")
        readonly = make_url(url).set(username='tp_test_ai', password='only_for_isolated_tests_492').render_as_string(hide_password=False)
        engine = make_engine(readonly)
        try:
            with engine.connect() as connection:
                assert connection.execute(text('SELECT COUNT(*) FROM orders')).scalar() == 120
                for sql in ('UPDATE orders SET pieces=1', 'DELETE FROM orders', 'DROP TABLE orders', 'SELECT * FROM sync_logs'):
                    with pytest.raises(DBAPIError):
                        connection.execute(text(sql))
                    connection.rollback()
        finally:
            engine.dispose()
        model = ToolModel(responses=[
            AIMessage(content='', tool_calls=[{'name': 'sql_db_query', 'args': {'query': "SELECT order_id, pieces FROM orders WHERE order_id='ORD-005'"}, 'id': 'call-1', 'type': 'tool_call'}]),
            AIMessage(content='The selected order quantity is supported by the executed SELECT.'),
        ])
        monkeypatch.setattr('app.services.ai_sql_service.ChatOpenAI', lambda **kwargs: model)
        service = AISQLService(Settings(database_url=url, ai_database_url=readonly, openai_api_key='test-model', workflow_db=tmp_path / 'agent.sqlite3'))
        try:
            first = service.ask('ORD-005 quantity?', None, '2026-04-01T09:00:00+08:00')
            assert first['queries'][0]['rows'][0]['order_id'] == 'ORD-005'
            original = first['queries'][0]['rows'][0]['pieces']
            with database.sessions.begin() as session:
                session.scalar(select(Order).where(Order.order_id == 'ORD-005')).pieces = original + 7
            second = service.ask('Refresh it', first['session_id'], '2026-04-01T09:01:00+08:00')
            assert second['queries'][0]['rows'][0]['pieces'] == original + 7
            with database.sessions.begin() as session:
                session.scalar(select(Order).where(Order.order_id == 'ORD-005')).pieces = original
        finally:
            service.close()
    finally:
        database.close()
