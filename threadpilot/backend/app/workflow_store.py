"""场景 3.1–3.3：SQLite 持久化、幂等操作、条件提醒与发送收据。"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Protocol

import httpx

from .schemas import DialogState, PendingAction
from .workflow_tools import DataTools


class Sender(Protocol):
    async def send(self, payload: dict[str, Any], idempotency_key: str) -> str:
        """场景 3.1：返回真实发送回执；实现必须支持幂等键。"""
        ...


class WebhookSender:
    def __init__(self, url: str, token: str) -> None:
        """场景 3.1：由服务端配置固定发送服务，用户不能控制目标 URL。"""
        self.url, self.token = url, token

    async def send(self, payload: dict[str, Any], idempotency_key: str) -> str:
        """场景 3.1：仅在发送服务明确返回 sent 和 receipt 时报告成功。"""
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self.url, json=payload, headers={
                'Authorization': f'Bearer {self.token}', 'Idempotency-Key': idempotency_key})
            response.raise_for_status()
            result = response.json()
            if result.get('status') != 'sent' or not result.get('receipt'):
                raise ValueError('Delivery not acknowledged')
            return str(result['receipt'])


class WorkflowStore:
    def __init__(self, path: Path) -> None:
        """场景 1.2/3.1–3.3：保存状态和审计到非静态目录。"""
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    kind TEXT NOT NULL, order_id TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, receipt TEXT);
                CREATE TABLE IF NOT EXISTS reminders (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    order_id TEXT NOT NULL, condition TEXT NOT NULL, deadline TEXT NOT NULL,
                    since TEXT NOT NULL, evaluated INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(session_id, order_id, condition));
                CREATE TABLE IF NOT EXISTS replies (event_id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
                    received_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    order_id TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """场景 3.1–3.3：事务提交或异常回滚，并关闭连接。"""
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def load(self, session_id: str) -> DialogState:
        """场景 1.2：只接受服务端已创建会话，拒绝客户端伪造状态。"""
        with self.connection() as db:
            row = db.execute('SELECT state FROM sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise KeyError('Unknown session')
        return DialogState.model_validate_json(row['state'])

    def save(self, state: DialogState) -> None:
        """场景 1.1–3.3：持久化一轮已完成的状态和有限历史。"""
        with self.connection() as db:
            db.execute('INSERT INTO sessions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state',
                       (state.session_id, state.model_dump_json()))

    def action_result(self, action_id: str, session_id: str) -> dict[str, Any] | None:
        """场景 3.1–3.3：确认重试按操作 ID 返回先前结果，跨会话不可读取。"""
        with self.connection() as db:
            row = db.execute('SELECT * FROM actions WHERE id=? AND session_id=?', (action_id, session_id)).fetchone()
        return dict(row) if row else None

    def commit_local(self, action: PendingAction, session_id: str, now: datetime) -> dict[str, Any]:
        """场景 3.2/3.3：备注和提醒在一个事务内落库；同条件提醒原位更新。"""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM actions WHERE id=?', (action.id,)).fetchone()
            if existing:
                return dict(existing)
            db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)',
                       (action.id, session_id, action.kind, action.order_id,
                        json.dumps(action.payload), 'saved', now.isoformat(), None))
            if action.kind == 'reminder':
                db.execute('''INSERT INTO reminders VALUES (?,?,?,?,?,?,0)
                    ON CONFLICT(session_id,order_id,condition) DO UPDATE SET
                    deadline=excluded.deadline, evaluated=0''',
                    (action.id, session_id, action.order_id, action.payload['condition'],
                     action.payload['deadline'], action.payload['since']))
        return {'id': action.id, 'status': 'saved', 'kind': action.kind, 'order_id': action.order_id}

    async def send(self, action: PendingAction, session_id: str, now: datetime, sender: Sender | None) -> dict[str, Any]:
        """场景 3.1：先记录意图，再幂等发送；不确定结果保留同一键用于安全重试。"""
        previous = self.action_result(action.id, session_id)
        if previous and previous['status'] == 'sent':
            return previous
        if sender is None:
            return {'status': 'not_sent', 'reason': 'Delivery connector is not configured. Draft remains unsent.'}
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO actions VALUES (?,?,?,?,?,?,?,?)',
                       (action.id, session_id, action.kind, action.order_id, json.dumps(action.payload),
                        'pending', now.isoformat(), None))
        try:
            receipt = await sender.send({**action.payload, 'order_id': action.order_id}, action.id)
        except (httpx.HTTPError, ValueError, OSError):
            return {'status': 'unknown', 'reason': 'Delivery not confirmed; retry with the same confirmation ID. No success claimed.'}
        with self.connection() as db:
            db.execute('UPDATE actions SET status=?, receipt=?, created_at=? WHERE id=?',
                       ('sent', receipt, now.isoformat(), action.id))
        return {'status': 'sent', 'receipt': receipt, 'id': action.id}

    def get_reminder(self, session_id: str, order_id: str, condition: str) -> dict[str, Any] | None:
        """场景 3.3：定位现有提醒供修改，防止重复创建。"""
        with self.connection() as db:
            row = db.execute('SELECT * FROM reminders WHERE session_id=? AND order_id=? AND condition=?',
                             (session_id, order_id, condition)).fetchone()
        return dict(row) if row else None

    def record_reply(self, event_id: str, order_id: str, received_at: datetime) -> None:
        """场景 3.3：供已认证消息集成写入真实回复事件，事件 ID 去重。"""
        if received_at.tzinfo is None:
            raise ValueError('Timezone is required')
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO replies VALUES (?,?,?)', (event_id, order_id, received_at.isoformat()))

    def evaluate_reminders(self, now: datetime, tools: DataTools) -> None:
        """场景 3.3：截止时重新读取条件；已满足则静默，未满足仅入站通知一次。"""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT * FROM reminders WHERE evaluated=0').fetchall():
                deadline = datetime.fromisoformat(row['deadline'])
                if deadline > now:
                    continue
                order = tools.refresh_order(row['order_id']).record
                since = datetime.fromisoformat(row['since'])
                if row['condition'] == 'no_reply':
                    replies = db.execute('SELECT received_at FROM replies WHERE order_id=?', (row['order_id'],)).fetchall()
                    satisfied = any(since <= datetime.fromisoformat(r['received_at']) <= deadline for r in replies)
                else:
                    activity_date = datetime.fromisoformat(order['last_activity_date']).date()
                    satisfied = since.date() < activity_date <= deadline.date()
                if not satisfied:
                    notification_id = f"{row['id']}:{row['deadline']}"
                    db.execute('INSERT OR IGNORE INTO notifications VALUES (?,?,?,?,?)',
                               (notification_id, row['session_id'], row['order_id'],
                                f"{row['condition']} condition unmet at {row['deadline']}; based on recorded data only.", now.isoformat()))
                db.execute('UPDATE reminders SET evaluated=1 WHERE id=?', (row['id'],))

    def notifications(self, session_id: str) -> list[dict[str, Any]]:
        """场景 3.3：读取会话内提醒结果，不向外部发送消息。"""
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM notifications WHERE session_id=? ORDER BY created_at', (session_id,))]
