"""场景 1.2：显式建表和首次导入。"""
from pathlib import Path
from alembic import command
from alembic.config import Config
from ..config import ROOT, Settings
from .session import Database
from ..services.importer import import_bytes


def initialize(files: list[Path], migrate: bool = True, dataset: str | None = None) -> None:
    """场景 1.2：先迁移再导入，重复导入不产生副本。"""
    if migrate:
        command.upgrade(Config(str(ROOT / 'backend/alembic.ini')), 'head')
    database = Database(Settings())
    try:
        for path in files:
            print(import_bytes(database, path.read_bytes(), path.name, dataset).model_dump_json())
    finally:
        database.close()
