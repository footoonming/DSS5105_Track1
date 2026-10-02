"""Protect public assets and contract after directory migration."""
import json
from pathlib import Path
from .test_api import client


def test_shared_data_and_static_paths(client):
    for url in ('/', '/ai-stream.js', '/assets/factory-hero.png', '/api/snapshot'):
        assert client.get(url).status_code == 200, url
    assert len(client.get('/api/snapshot').json()['orders']) == 120
    for url in ('/.env', '/backend/.env', '/app/main.py', '/data/orders.csv', '/data/raw/source.xlsx', '/data/dialogs.xlsx'):
        assert client.get(url).status_code == 404, url


def test_export_matches_runtime(client):
    schema = client.get('/openapi.json').json()
    assert schema['servers'][0]['url'] == 'http://127.0.0.1:8000'
    assert 'text/event-stream' in schema['paths']['/api/v1/workflow/chat/stream']['post']['responses']['200']['content']
    exported = Path(__file__).resolve().parents[2] / 'docs' / 'openapi.json'
    assert schema == json.loads(exported.read_text(encoding='utf-8'))
