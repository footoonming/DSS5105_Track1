"""场景 1.1–3.3：验证工作流 SSE，不再测试模型 token 转发。"""
import json

import httpx
from fastapi.testclient import TestClient

from app.schemas import Classification, Intent, Slots
from app.streaming import event
from .test_api import client, provider
from .test_workflow import provider_response


def test_event_unicode() -> None:
    """场景 1.1–3.3：SSE 编码保留换行、Unicode 和 JSON 转义。"""
    text = 'Hello\n“世界” 👋'
    frame = event('delta', {'text': text})
    assert frame.startswith('event: delta\n')
    assert json.loads(frame.splitlines()[1].removeprefix('data: '))['text'] == text


def test_workflow_stream_metadata(client: TestClient) -> None:
    """场景 1.1：规则验证后返回完整 answer delta 和可信元数据。"""
    provider(client, lambda _: provider_response(Classification(intent=Intent.ORDER_LOOKUP, slots=Slots(order_ids=['ORD-005']), confidence=.99)))
    response = client.post('/api/v1/workflow/chat/stream', json={'message': 'Open ORD-005'})
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    frames = [(frame.splitlines()[0].removeprefix('event: '),
               json.loads(frame.splitlines()[1].removeprefix('data: ')))
              for frame in response.text.strip().split('\n\n')]
    assert [name for name, _ in frames] == ['start', 'delta', 'done']
    assert frames[1][1]['text'] == frames[2][1]['answer']
    assert frames[2][1]['state']['active_order'] == 'ORD-005'
    assert frames[2][1]['request_id'] == response.headers['x-request-id']


def test_stream_errors_before_sse(client: TestClient) -> None:
    """场景 1.1–3.3：模型错误在建立 SSE 前返回非 200 JSON。"""
    path = '/api/v1/workflow/chat/stream'
    assert client.post(path, json={'message': 'Hi'}).status_code == 503
    provider(client, lambda _: httpx.Response(429, json={'error': {'message': 'PRIVATE_DETAIL'}}))
    response = client.post(path, json={'message': 'Hi'})
    assert response.status_code == 429
    assert response.json()['error']['code'] == 'MODEL_RATE_LIMITED'
    assert 'PRIVATE_DETAIL' not in response.text
