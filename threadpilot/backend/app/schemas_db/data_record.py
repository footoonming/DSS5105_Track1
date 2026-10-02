"""场景 1.1–2.2：显式列类型及表格/API 共用校验。"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_serializer

Dataset = Literal['orders', 'production_log', 'workshops']
Stage = Literal['KNITTING', 'ASSEMBLY', 'WASHING', 'PACKING']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class OrderFields(Strict):
    order_id: str = Field(pattern=r'^ORD-\d{3}$')
    customer: str = Field(min_length=1, max_length=200)
    product: str = Field(min_length=1, max_length=200)
    category: Literal['TOPS', 'ACCESSORIES']
    pieces: int = Field(gt=0)
    order_date: date
    due_date: date
    status: Literal['IN_PROGRESS', 'COMPLETE']
    current_stage: Literal['KNITTING', 'ASSEMBLY', 'WASHING', 'PACKING', 'COMPLETE']
    last_activity_date: date
    completed_date: date | None = None
    days_late: int | None = None

    @model_validator(mode='after')
    def coherent(self) -> 'OrderFields':
        """场景 1.3：完成事实、工序和日期必须一致。"""
        if self.due_date < self.order_date or self.last_activity_date < self.order_date:
            raise ValueError('Dates precede order_date')
        if self.status == 'COMPLETE':
            if not self.completed_date or self.current_stage != 'COMPLETE':
                raise ValueError('Completed orders require completed_date and COMPLETE stage')
            if self.completed_date < self.order_date:
                raise ValueError('Invalid completed_date')
        elif self.completed_date or self.current_stage == 'COMPLETE' or self.days_late is not None:
            raise ValueError('Active orders cannot contain completion facts')
        return self


class ProductionFields(Strict):
    date: date
    stage: Stage
    pieces_completed: int = Field(ge=0)


class WorkshopFields(Strict):
    workshop_id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    capacity_pieces_per_day: int = Field(gt=0)
    pickup_lead_days: int = Field(ge=0)
    defect_rate: Decimal = Field(ge=0, le=1, decimal_places=6)
    cost_per_piece: Decimal = Field(ge=0, decimal_places=4)
    makes: Literal['TOPS', 'ACCESSORIES', 'TOPS+ACCESSORIES']
    status: Literal['ACTIVE', 'SUSPENDED']
    max_batch_pieces: int | None = Field(default=None, gt=0)
    current_queue_days: Decimal = Field(ge=0, decimal_places=4)
    notes: str | None = None


    @field_serializer('defect_rate', 'cost_per_piece', 'current_queue_days', when_used='json')
    def canonical_decimal(self, value: Decimal) -> str:
        """场景 1.2：MySQL 定点尾零不应造成虚假增量或冲突。"""
        return format(value.normalize(), 'f')


class RecordWrite(Strict):
    dataset: Dataset = 'orders'
    data: dict[str, Any]
    expected_version: int | None = Field(default=None, ge=1)


class RecordRead(Strict):
    id: int
    dataset: Dataset
    data: dict[str, Any]
    version: int
    source: str
    source_row: int | None
    created_at: datetime
    updated_at: datetime
