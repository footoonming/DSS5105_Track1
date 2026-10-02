"""场景 1.2：显式白名单文件的周期同步。"""
import hashlib
import logging
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from ..config import Settings
from ..db.session import Database
from ..models import SyncLog
from .importer import import_bytes


class SyncService:
    def __init__(self, database: Database, settings: Settings) -> None:
        """场景 1.2：不扫描场景表或其他非业务文件。"""
        self.database, self.settings = database, settings
        self.scheduler = BackgroundScheduler(timezone='UTC')

    def check(self) -> None:
        """场景 1.2：内容哈希变化才导入；失败保留旧检查点以便重试。"""
        root = self.settings.raw_data_dir.resolve()
        for filename in self.settings.sync_files:
            try:
                path = (root / filename).resolve()
                if not path.is_relative_to(root) or path.suffix.lower() not in ('.xlsx', '.csv'):
                    raise ValueError('Sync path must stay inside raw_data_dir')
                before = path.stat()
                content = path.read_bytes()
                after = path.stat()
                if before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size:
                    continue
                if len(content) > self.settings.max_upload_bytes:
                    raise ValueError('Sync file too large')
                digest = hashlib.sha256(content).hexdigest()
                with self.database.sessions() as session:
                    previous = session.scalar(select(SyncLog).where(SyncLog.source == path.name, SyncLog.status == 'success').order_by(SyncLog.id.desc()).limit(1))
                    unchanged = previous is not None and previous.file_hash == digest
                if not unchanged:
                    import_bytes(self.database, content, path.name)
            except Exception:
                logging.getLogger(__name__).warning('Sync failed for configured file %s; previous data retained', Path(filename).name)

    def start(self) -> None:
        """场景 1.2：避免单进程重叠运行，数据库锁处理跨进程写入。"""
        if self.settings.sync_enabled:
            self.scheduler.add_job(self.check, 'interval', minutes=self.settings.sync_interval_minutes, max_instances=1, coalesce=True)
            self.scheduler.start()

    def close(self) -> None:
        """场景 1.2：退出前等待当前导入事务完成。"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
