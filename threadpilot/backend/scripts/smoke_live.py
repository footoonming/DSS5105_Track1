"""场景 1.1：通过当前 JSON 工作流验证真实模型，不打印密钥。"""
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    health = client.get('/api/v1/health').json()
    print({'configured': health['configured'], 'model': health['model']})
    result = client.post('/chat', json={'message': 'Open ORD-005.'})
    if result.status_code == 200:
        data = result.json()
        print({'status': 200, 'answer': data['answer'], 'usage': data['usage']})
    else:
        print({'status': result.status_code, 'error': result.json().get('error', {}).get('code')})
        raise SystemExit(1)
