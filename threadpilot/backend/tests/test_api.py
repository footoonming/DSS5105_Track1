"""场景 1.1–3.3：工作流 HTTP 契约与服务端错误处理。"""
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app.main import create_app
from app.schemas import Classification, Intent, Slots
from .test_workflow import provider_response


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    """场景 1.1–3.3：隔离配置和数据库，不使用真实密钥。"""
    monkeypatch.setenv('OPENAI_API_KEY', '')
    monkeypatch.setenv('WORKFLOW_DB', str(tmp_path / 'workflow.sqlite3'))
    monkeypatch.setenv('CHASE_WEBHOOK_URL', '')
    monkeypatch.setenv('BUSINESS_NOW', '2026-04-01T09:00:00+08:00')
    with TestClient(create_app()) as value:
        yield value


def provider(client: TestClient, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    """场景 1.1–3.3：将真实 SDK 连接到可控 HTTP 替身。"""
    client.app.state.client = AsyncOpenAI(api_key='test-key-never-real', max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_missing_key_and_static_safety(client: TestClient) -> None:
    """场景 1.1：无密钥明确失败，私有路径不公开。"""
    assert client.get('/api/v1/health').json()['configured'] is False
    response = client.post('/chat', json={'message': 'Hello'})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'API_KEY_NOT_CONFIGURED'
    assert response.headers['x-request-id']
    for path in ('/.env', '/backend/.env'):
        assert client.get(path).status_code == 404
    assert client.get('/').status_code == 200


def test_actual_sdk_workflow_contract(client: TestClient) -> None:
    """场景 1.1：真实 SDK 解析意图，JSON 别名共享服务端会话。"""
    def handler(request: httpx.Request) -> httpx.Response:
        """场景 1.1：只模拟模型提取，答案由正式数据生成。"""
        payload = json.loads(request.content)
        assert request.url.path == '/v1/responses'
        assert payload['store'] is False
        assert payload['text']['format']['type'] == 'json_schema'
        return provider_response(Classification(intent=Intent.ORDER_LOOKUP, slots=Slots(order_ids=['ORD-005']), confidence=.99))
    provider(client, handler)
    response = client.post('/api/v1/workflow/chat', json={'message': 'Open ORD-005'})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['state']['active_order'] == 'ORD-005'
    assert data['intent'] == 'order.lookup'
    assert data['evidence'][0]['record']['order_id'] == 'ORD-005'
    assert data['request_id'] == response.headers['x-request-id']


@pytest.mark.parametrize('status,expected,code', [(401,502,'MODEL_API_ERROR'), (429,429,'MODEL_RATE_LIMITED'), (500,502,'MODEL_API_ERROR')])
def test_upstream_errors_redacted(client: TestClient, status: int, expected: int, code: str) -> None:
    """场景 1.1–3.3：隐藏上游错误原文。"""
    provider(client, lambda _: httpx.Response(status, json={'error': {'message': 'SECRET_PROVIDER_DETAIL', 'type': 'test'}}))
    response = client.post('/chat', json={'message': 'Hello'})
    assert response.status_code == expected
    assert response.json()['error']['code'] == code
    assert 'SECRET_PROVIDER_DETAIL' not in response.text


def test_timeout(client: TestClient) -> None:
    """场景 1.1–3.3：模型超时映射为 504。"""
    def handler(request: httpx.Request) -> httpx.Response:
        """场景 1.1：模拟网络读取超时。"""
        raise httpx.ReadTimeout('private', request=request)
    provider(client, handler)
    assert client.post('/chat', json={'message': 'Hi'}).status_code == 504


def test_removed_routes_and_request_models(client: TestClient) -> None:
    """场景 1.1–3.3：已移除的路由不可调用，也不接受旧上下文字段。"""
    schema = client.get('/openapi.json').json()
    for path in ('/api/v1/chat', '/api/v1/chat/stream'):
        assert path not in schema['paths']
        # StaticFiles mounts / and rejects POST with 405; neither path is an API.
        assert client.post(path, json={'message': 'Hello'}).status_code in (404, 405)
    for extra in ({'history': []}, {'context': {}}, {'stream': True}):
        assert client.post('/chat', json={'message': 'Hi', **extra}).status_code == 422
    assert not any(name in schema['components']['schemas'] for name in ('HistoryMessage', 'PageContext', 'ModelAnswer', 'Usage'))


def test_cors(client: TestClient) -> None:
    """场景 1.1–3.3：保留工作流页面的跨域预检契约。"""
    response = client.options('/chat', headers={'Origin': 'http://127.0.0.1:8765', 'Access-Control-Request-Method': 'POST'})
    assert response.headers['access-control-allow-origin'] == 'http://127.0.0.1:8765'
