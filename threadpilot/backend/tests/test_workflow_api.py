"""场景 1.1–3.3：FastAPI、SSE、证据及回复集成契约。"""
from pathlib import Path
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from .test_workflow import FixedClassifier


@pytest.fixture
def workflow_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """场景 1.1–3.3：不读取真实密钥、不复用开发数据库的测试客户端。"""
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('WORKFLOW_DB', str(tmp_path / 'api.sqlite3'))
    monkeypatch.setenv('BUSINESS_NOW', '2026-04-01T09:00:00+08:00')
    monkeypatch.setenv('CHASE_WEBHOOK_URL', '')
    monkeypatch.setenv('REPLY_INGEST_TOKEN', 'test-reply-secret')
    with TestClient(create_app()) as client:
        yield client


def test_json_and_sse_share_server_state(workflow_client: TestClient) -> None:
    """场景 1.1/1.2：JSON 与 SSE 共用会话，来源行可访问且无客户端伪造状态。"""
    client = workflow_client
    assert client.post('/chat', json={'message': 'Hello'}).status_code == 503
    client.app.state.intent_classifier = FixedClassifier('order.lookup', order_ids=['ORD-005'])
    response = client.post('/chat', json={'message': 'Open ORD-005.'})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['state']['active_order'] == 'ORD-005'
    assert data['request_id'] == response.headers['x-request-id']
    evidence = client.get(data['evidence'][0]['url']).json()
    assert evidence['record']['order_id'] == 'ORD-005'
    session = data['state']['session_id']
    client.app.state.intent_classifier = FixedClassifier('order.refresh', reference='active')
    response = client.post('/api/v1/workflow/chat/stream', json={'message': 'Has it moved?', 'session_id': session})
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert 'event: done' in response.text and 'ORD-005' in response.text
    assert '"active_order": "ORD-005"' in response.text
    assert client.post('/chat', json={'message': 'Hi', 'state': {'active_order': 'ORD-999'}}).status_code == 422
    assert client.post('/chat', json={'message': ' '}).status_code == 422
    assert client.get('/api/v1/evidence/private.csv/2').status_code == 404
    assert client.get('/api/v1/evidence/orders.csv/0').status_code == 404
    assert client.get('/runtime/workflow.sqlite3').status_code == 404


def test_reply_ingestion_authentication_and_idempotency(workflow_client: TestClient) -> None:
    """场景 3.3：真实回复接入必须认证，不接受未知订单或未来事件。"""
    client = workflow_client
    payload = {'event_id': 'evt-1', 'order_id': 'ORD-005', 'received_at': '2026-04-01T08:00:00+08:00'}
    assert client.post('/api/v1/workflow/replies', json=payload).status_code == 401
    headers = {'Authorization': 'Bearer test-reply-secret'}
    assert client.post('/api/v1/workflow/replies', headers=headers, json=payload).status_code == 200
    assert client.post('/api/v1/workflow/replies', headers=headers, json=payload).status_code == 200
    with client.app.state.workflow.store.connection() as db:
        assert db.execute('SELECT COUNT(*) FROM replies').fetchone()[0] == 1
    assert client.post('/api/v1/workflow/replies', headers=headers, json={**payload, 'order_id': 'ORD-999'}).status_code == 422
    assert client.post('/api/v1/workflow/replies', headers=headers, json={**payload, 'received_at': '2026-04-02T12:00:00+08:00'}).status_code == 422


def test_guessed_order_does_not_bypass_clarification(workflow_client: TestClient) -> None:
    """场景 1.1/3.2：模型猜中的 ID 仍不能替代用户选择或备注目标确认。"""
    client = workflow_client
    client.app.state.intent_classifier = FixedClassifier('order.lookup', order_ids=['ORD-005'], customer='TrendCart')
    result = client.post('/chat', json={'message': 'Show the TrendCart order.'}).json()
    assert result['needs_clarification'] and result['state']['active_order'] is None
    client.app.state.intent_classifier = FixedClassifier('execution.note', order_ids=['ORD-005'], text='Escalated today.')
    result = client.post('/chat', json={'message': 'Add a note that we escalated this today.', 'selected_order_id': 'ORD-005'}).json()
    assert result['needs_clarification'] and 'correct order' in result['answer']
    assert not result['confirmation_required']
