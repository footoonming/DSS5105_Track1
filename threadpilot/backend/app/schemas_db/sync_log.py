"""场景 1.2：同步结果契约。"""
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class SyncRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    source: str
    file_hash: str
    status: str
    inserted: int
    updated: int
    skipped: int
    message: str
    created_at: datetime
