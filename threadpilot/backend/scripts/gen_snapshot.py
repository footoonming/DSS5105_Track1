"""场景 1.2：导出数据库快照，不覆盖前端加载器。"""
import json
from app.config import ROOT, Settings
from app.db.session import Database
from app.services.snapshot_service import snapshot
from app.workflow_api import business_now


def main() -> None:
    """场景 1.2：导出的 JSON 只用于离线核对。"""
    database = Database(Settings())
    try:
        target = ROOT / 'data/snapshots/data.snapshot.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(snapshot(database, business_now().date().isoformat()), ensure_ascii=False, indent=2), encoding='utf-8')
        print(target)
    finally:
        database.close()


if __name__ == '__main__':
    main()
