"""场景 1.1–2.2：来自正式业务表格的类型化表结构。"""
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base


def utcnow() -> datetime:
    """场景 1.2：数据库时间统一存储 UTC。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DataRecord:
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    source: Mapped[str] = mapped_column(String(255), default='api')
    source_row: Mapped[int | None] = mapped_column(Integer)
    imported_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)


class Order(DataRecord, Base):
    __tablename__ = 'orders'
    order_id: Mapped[str] = mapped_column(String(32), unique=True)
    customer: Mapped[str] = mapped_column(String(200), index=True)
    product: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32))
    pieces: Mapped[int] = mapped_column(Integer)
    order_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    current_stage: Mapped[str] = mapped_column(String(32))
    last_activity_date: Mapped[date] = mapped_column(Date)
    completed_date: Mapped[date | None] = mapped_column(Date)
    days_late: Mapped[int | None] = mapped_column(Integer)


class ProductionRecord(DataRecord, Base):
    __tablename__ = 'production_log'
    __table_args__ = (UniqueConstraint('date', 'stage', name='uq_production_date_stage'),)
    date: Mapped[date] = mapped_column(Date, index=True)
    stage: Mapped[str] = mapped_column(String(32))
    pieces_completed: Mapped[int] = mapped_column(Integer)


class Workshop(DataRecord, Base):
    __tablename__ = 'workshops'
    workshop_id: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    capacity_pieces_per_day: Mapped[int] = mapped_column(Integer)
    pickup_lead_days: Mapped[int] = mapped_column(Integer)
    defect_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    cost_per_piece: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    makes: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    max_batch_pieces: Mapped[int | None] = mapped_column(Integer)
    current_queue_days: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    notes: Mapped[str | None] = mapped_column(Text)


class SyncLock(Base):
    __tablename__ = 'sync_lock'
    id: Mapped[int] = mapped_column(primary_key=True)


class Tombstone(Base):
    __tablename__ = 'data_tombstones'
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
