"""场景 1.1–3.3：工作流 SSE 事件编码。"""
import json
from typing import Any


def event(name: str, data: dict[str, Any]) -> str:
    """场景 1.1–3.3：编码已验证的工作流事件，保留 Unicode 文本。"""
    return f'event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'
