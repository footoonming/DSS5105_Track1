"""场景 1.1–3.3：实时读取、增量保护、迁移与 SQL 安全回归。"""
from io import BytesIO
from pathlib import Path
import csv
import io
import pandas as pd
import pytest
from sqlalchemy import select, func
from app.models import Order, SyncLog
from app.crud.data_record import fields
from app.services.importer import import_bytes, parse_file, ImportConflict
from app.services.sync_service import SyncService
from app.services.ai_sql_service import validate_sql
from app.config import Settings
from .test_api import client
from .test_workflow import FixedClassifier

AUTH = {'Authorization': 'Bearer test-management-token', 'X-Confirm-Write': 'true'}


def order_csv(row: dict) -> bytes:
    """场景 1.2：序列化一条真实记录用于增量边界验证。"""
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    return stream.getvalue().encode()


def test_idempotency_excel_and_conflicts(business_database) -> None:
    """场景 1.2：批量导入幂等、空值一致，API 修改不被旧文件覆盖。"""
    database = business_database
    path = Path(__file__).resolve().parents[2] / 'data/orders.csv'
    assert import_bytes(database, path.read_bytes(), path.name).skipped == 120
    with database.sessions() as session:
        record = session.scalar(select(Order).where(Order.order_id == 'ORD-005'))
        original = fields('orders', record)
        record_id = record.id
    output = BytesIO()
    pd.DataFrame([original, original]).to_excel(output, index=False, sheet_name='orders')
    assert len(parse_file(output.getvalue(), 'source.xlsx')['orders']) == 1
    assert import_bytes(database, output.getvalue(), 'source.xlsx').skipped == 1
    with database.sessions.begin() as session:
        session.get(Order, record_id).pieces += 11
    assert import_bytes(database, order_csv(original), 'orders.csv').skipped == 1
    changed = {**original, 'pieces': original['pieces'] + 22}
    with pytest.raises(ImportConflict):
        import_bytes(database, order_csv(changed), 'orders.csv')
    with database.sessions() as session:
        assert session.get(Order, record_id).pieces == original['pieces'] + 11
        assert session.scalar(select(SyncLog).order_by(SyncLog.id.desc()).limit(1)).status == 'failed'


def test_api_refresh_confirmation_version_and_tombstone(client, business_database) -> None:
    """场景 1.2/3.2：一次 PUT 后快照和下一轮意图问答读取新值。"""
    client.app.state.intent_classifier = FixedClassifier('order.lookup', order_ids=['ORD-005'])
    chat = client.post('/chat', json={'message': 'Open ORD-005'}).json()
    row = client.get(chat['evidence'][0]['url']).json()
    new = {**row['data'], 'current_stage': 'ASSEMBLY', 'last_activity_date': '2026-04-01'}
    body = {'dataset': 'orders', 'data': new, 'expected_version': row['version']}
    url = f"/api/data/{row['id']}"
    assert client.put(url, json=body).status_code == 401
    assert client.put(url, json=body, headers={'Authorization': AUTH['Authorization']}).status_code == 409
    assert client.put(url, json=body, headers=AUTH).status_code == 200
    assert client.put(url, json=body, headers=AUTH).status_code == 409
    assert next(r for r in client.get('/api/snapshot').json()['orders'] if r['order_id'] == 'ORD-005')['current_stage'] == 'ASSEMBLY'
    client.app.state.intent_classifier = FixedClassifier('order.refresh', reference='active')
    refreshed = client.post('/chat', json={'message': 'Has it moved?', 'session_id': chat['state']['session_id']}).json()
    assert 'ASSEMBLY' in refreshed['answer']
    assert 'CSV snapshot' not in refreshed['answer']
    assert client.delete(url + '?expected_version=2', headers=AUTH).status_code == 204
    assert import_bytes(business_database, order_csv(row['data']), 'orders.csv').skipped == 1
    assert client.get(url).status_code == 404


def test_upload_validation_atomicity_and_logs(client, business_database) -> None:
    """场景 1.2：错误上传不产生部分写入，同步审计可查。"""
    bad = b'order_id,customer\nORD-999,Acme\n'
    assert client.post('/api/sync/import', files={'file': ('orders.csv', bad)}, headers=AUTH).status_code == 422
    with business_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 120
    assert client.get('/api/sync/logs', headers=AUTH).json()[0]['status'] == 'failed'
    assert client.post('/api/sync/import', files={'file': ('other.csv', bad)}, headers=AUTH).status_code == 422


def test_scheduler_hash_change(business_database, tmp_path) -> None:
    """场景 1.2：持久检查点避免重复同步，文件改变后更新原 ID。"""
    with business_database.sessions() as session:
        record = session.scalar(select(Order).where(Order.order_id == 'ORD-005'))
        values, record_id = fields('orders', record), record.id
    path = tmp_path / 'orders.csv'
    path.write_bytes(order_csv(values))
    service = SyncService(business_database, Settings(raw_data_dir=tmp_path, sync_files=['orders.csv']))
    service.check()
    with business_database.sessions() as session:
        before = session.scalar(select(func.count()).select_from(SyncLog))
    service.check()
    with business_database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SyncLog)) == before
    path.write_bytes(order_csv({**values, 'pieces': values['pieces'] + 1}))
    service.check()
    with business_database.sessions() as session:
        assert session.get(Order, record_id).pieces == values['pieces'] + 1


@pytest.mark.parametrize('sql', [
    'DELETE FROM orders', 'SELECT * FROM orders; DROP TABLE orders',
    'SELECT * FROM mysql.user', 'SELECT * FROM sync_logs',
    'SELECT SLEEP(5) FROM orders', 'SELECT LOAD_FILE("secret") FROM orders',
    'SELECT * FROM orders INTO OUTFILE "x"', 'SELECT * FROM orders FOR UPDATE',
    'SELECT @x:=1 FROM orders', 'SELECT /*comment*/ * FROM orders',
    'WITH x AS (SELECT * FROM orders) SELECT * FROM x',
    'SELECT * FROM orders LIMIT -1', 'SELECT GET_LOCK("a",1) FROM orders',
])
def test_sql_rejects_writes_and_escapes(sql: str) -> None:
    """场景 1.2：写 SQL、多语句、锁、文件函数及系统表均被拒绝。"""
    with pytest.raises(ValueError):
        validate_sql(sql, 100)


def test_sql_allows_aggregation_and_caps_rows() -> None:
    """场景 1.4/2.1：允许透明聚合，强制结果上限。"""
    assert 'LIMIT 100' in validate_sql('SELECT customer, SUM(pieces) FROM orders GROUP BY customer LIMIT 9999', 100)
    assert 'LIMIT 3' in validate_sql('SELECT order_id FROM orders LIMIT 3', 100)


def test_sql_api_unconfigured_fails_closed(client) -> None:
    """场景 1.2：只读连接缺失时不会退回读写数据库或静态表格。"""
    response = client.post('/api/ai/ask', json={'message': 'List orders'})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'SQL_AGENT_UNAVAILABLE'


def test_create_delete_and_explicit_recreate(client) -> None:
    """场景 1.2/3.2：覆盖标准 CRUD 的新建、读取和显式重建语义。"""
    body = {'dataset': 'production_log', 'data': {'date': '2026-04-01', 'stage': 'KNITTING', 'pieces_completed': 800}}
    created = client.post('/api/data', json=body, headers=AUTH)
    assert created.status_code == 201, created.text
    record = created.json()
    url = f"/api/data/{record['id']}?dataset=production_log"
    assert client.get(url).json()['data']['pieces_completed'] == 800
    assert client.post('/api/data', json=body, headers=AUTH).status_code == 409
    assert client.delete(url + '&expected_version=1', headers=AUTH).status_code == 204
    assert client.get(url).status_code == 404
    assert client.post('/api/data', json=body, headers=AUTH).status_code == 201


def test_malformed_workbook_is_client_error(client) -> None:
    """场景 1.2：损坏的工作簿不会变成服务器内部错误。"""
    response = client.post('/api/sync/import', files={'file': ('source.xlsx', b'not a zip archive')}, headers=AUTH)
    assert response.status_code == 422


def test_compatible_chat_completion_classifier(client) -> None:
    """场景 1.1：兼容网关 JSON mode 仍执行结构校验和原意图路由。"""
    import httpx
    import json
    from .test_api import provider
    from app.schemas import Classification, Intent, Slots
    client.app.state.settings.intent_api_style = 'chat_completions'

    def handler(request: httpx.Request) -> httpx.Response:
        """场景 1.1：模拟 Chat Completions 的标准 JSON 响应。"""
        payload = json.loads(request.content)
        assert request.url.path == '/v1/chat/completions'
        assert payload['response_format'] == {'type': 'json_object'}
        result = Classification(intent=Intent.ORDER_LOOKUP, slots=Slots(order_ids=['ORD-005']), confidence=.99)
        return httpx.Response(200, json={'id': 'chat-test', 'object': 'chat.completion', 'created': 1, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': result.model_dump_json()}}]})

    provider(client, handler)
    result = client.post('/chat', json={'message': 'Open ORD-005'})
    assert result.status_code == 200, result.text
    assert result.json()['state']['active_order'] == 'ORD-005'
