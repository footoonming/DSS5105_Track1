"""场景 1.1–3.3：工作流的结构化边界与服务端状态。"""
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Intent(StrEnum):
    ORDER_LOOKUP = 'order.lookup'
    ORDER_REFRESH = 'order.refresh'
    ORDER_RISK = 'order.risk'
    ORDER_COMPARE = 'order.compare'
    ORDER_COMMITMENT = 'order.commitment'
    ORDER_PRIORITIZE = 'order.prioritize'
    OPERATIONS_NORMALITY = 'operations.normality'
    OPERATIONS_DEVIATION = 'operations.deviation'
    EXECUTION_CHASE = 'execution.chase'
    EXECUTION_NOTE = 'execution.note'
    EXECUTION_REMINDER = 'execution.reminder'
    UNKNOWN = 'unknown'


class Slots(StrictModel):
    order_ids: list[str] = Field(default_factory=list, max_length=10)
    customer: str | None = None
    product: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    due_date: str | None = None
    stage: Literal['KNITTING', 'ASSEMBLY', 'WASHING', 'PACKING'] | None = None
    target_date: str | None = None
    observed_output: int | None = Field(default=None, ge=0)
    baseline: Literal['same_weekday'] | None = None
    comparison_fields: list[Literal['due_date', 'last_activity_date', 'current_stage', 'status']] = Field(default_factory=list)
    criterion: Literal['due_date', 'last_activity_date'] | None = None
    window_days: int | None = Field(default=None, ge=0, le=365)
    delivery_point: Literal['factory', 'customer'] | None = None
    delivery_buffer_days: int | None = Field(default=None, ge=0, le=60)
    packing_loss_days: int | None = Field(default=None, ge=0, le=60)
    recipient: str | None = None
    tone: str | None = None
    text: str | None = None
    deadline: str | None = None
    condition: Literal['no_reply', 'no_activity'] | None = None
    action: Literal['read', 'draft', 'revise', 'send', 'save', 'create', 'update', 'explain', 'evidence', 'recommend', 'rank', 'confirm_target'] = 'read'
    reference: Literal['explicit', 'active', 'ambiguous', 'none'] = 'none'


class Classification(StrictModel):
    intent: Intent
    slots: Slots = Field(default_factory=Slots)
    confidence: float = Field(ge=0, le=1)
    needs_clarification: bool = False
    clarification_question: str | None = None


class Evidence(StrictModel):
    source: str
    row: int
    url: str
    record: dict[str, str]
    record_id: int | None = None
    version: int | None = None
    updated_at: str | None = None
    original_source: str | None = None


class ToolCall(StrictModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    idempotent: bool = True
    requires_confirmation: bool = False
    executed: bool = True


class PendingClarification(StrictModel):
    intent: Intent
    question: str
    slots: Slots
    candidates: list[str] = Field(default_factory=list)


class PendingAction(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: Literal['send', 'note', 'reminder']
    order_id: str
    payload: dict[str, Any]
    preview: str
    created_at: datetime
    source_snapshot: dict[str, str] = Field(default_factory=dict)


class DialogState(StrictModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    active_order: str | None = None
    active_customer: str | None = None
    pending_clarification: PendingClarification | None = None
    pending_action: PendingAction | None = None
    last_intent: Intent | None = None
    slots: Slots = Field(default_factory=Slots)
    comparison_orders: list[str] = Field(default_factory=list)
    last_order_ids: list[str] = Field(default_factory=list)
    draft: dict[str, str] | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    revision: int = 0


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=1500)
    session_id: str | None = Field(default=None, pattern=r'^[a-f0-9-]{36}$')
    confirmation_id: str | None = None
    selected_order_id: str | None = Field(default=None, pattern=r'^ORD-\d{3}$')


class ChatResponse(StrictModel):
    answer: str
    intent: Intent
    slots: Slots
    confidence: float
    needs_clarification: bool = False
    clarification_question: str | None = None
    confirmation_required: bool = False
    confirmation_id: str | None = None
    state: DialogState
    tool_calls: list[ToolCall] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    order_ids: list[str] = Field(default_factory=list)
    selected_order_id: str | None = None
    sources: list[str] = Field(default_factory=list)
    request_id: str = ''
    model: str = 'gpt-4.1'
    business_date: str
    usage: dict[str, int] | None = None
