"""场景 1.1–2.2：通用只读 SQL 问答入口。"""
import threading
from typing import Any
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from ..services.ai_sql_service import AISQLService
from ..workflow_api import business_now

router = APIRouter(tags=['SQL Agent'])
initialization_lock = threading.Lock()


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    session_id: UUID | None = None


class QueryEvidence(BaseModel):
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    possibly_truncated: bool
    queried_at: str


class AskResponse(BaseModel):
    session_id: UUID
    answer: str
    business_time: str
    queries: list[QueryEvidence]


@router.post('/api/ai/ask', response_model=AskResponse)
def ask(body: AskRequest, request: Request) -> dict[str, Any]:
    """场景 1.1–2.2：独立会话不会混入原工作流的待确认操作。"""
    if not body.message.strip():
        raise HTTPException(422, {'code': 'EMPTY_MESSAGE', 'message': 'Message cannot be blank.'})
    with initialization_lock:
        if getattr(request.app.state, 'sql_agent', None) is None:
            try:
                request.app.state.sql_agent = AISQLService(request.app.state.settings)
            except Exception:
                raise HTTPException(503, {'code': 'SQL_AGENT_UNAVAILABLE', 'message': 'Check the model configuration, migrations and independent SELECT-only database account.'})
    try:
        return request.app.state.sql_agent.ask(body.message, str(body.session_id) if body.session_id else None, business_now().isoformat())
    except KeyError:
        raise HTTPException(404, {'code': 'UNKNOWN_SESSION', 'message': 'Start a new SQL conversation.'})
    except Exception:
        raise HTTPException(502, {'code': 'SQL_AGENT_FAILED', 'message': 'Model/query processing failed; no write was performed.'})
