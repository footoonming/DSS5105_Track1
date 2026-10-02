"""场景 1.1：验证运行中服务的工作流 SSE；不打印密钥。"""
import json
import httpx

deltas = 0
done = False
with httpx.stream('POST', 'http://127.0.0.1:8000/api/v1/workflow/chat/stream', json={'message': 'Open ORD-005.'}, timeout=100) as response:
    print({'http_status': response.status_code})
    response.raise_for_status()
    name = ''
    for line in response.iter_lines():
        if line.startswith('event: '):
            name = line[7:]
        elif line.startswith('data: '):
            payload = json.loads(line[6:])
            if name == 'delta':
                deltas += 1
            elif name == 'error':
                print({'error': payload['code']})
                raise SystemExit(1)
            elif name == 'done':
                done = True
                print({'delta_events': deltas, 'answer': payload['answer'], 'model': payload['model']})
if not done or not deltas:
    raise SystemExit('No complete streaming answer received')
