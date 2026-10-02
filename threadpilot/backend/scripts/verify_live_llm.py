"""场景 1.1–3.3：真实模型、MySQL 和原工作流的可复现验证。"""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.config import ROOT, Settings
from app.db.session import Database
from app.intent_classifier import IntentClassifier
from app.models import Order
from app.schemas import ChatRequest, DialogState
from app.services.ai_sql_service import AISQLService
from app.services.snapshot_service import DatabaseDataTools
from app.workflow_engine import WorkflowEngine
from app.workflow_store import WorkflowStore
from tests.test_workflow import NOW, SCENARIOS, WORKBOOK, RecordingSender


def save(path: Path, report: dict[str, Any]) -> None:
    """场景 1.1–3.3：逐轮持久化报告，保留失败结果而非只展示成功样例。"""
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


async def evaluate() -> None:
    """场景 1.1–3.3：真实提取 45 轮；发送替身和私有会话隔离外部副作用。"""
    settings = Settings()
    rw = os.environ.get('LIVE_DATABASE_URL', settings.database_url.get_secret_value())
    ro = os.environ.get('LIVE_AI_DATABASE_URL', settings.ai_database_url.get_secret_value())
    if make_url(rw).database != 'threadpilot_test':
        raise ValueError('Live evaluation only permits the dedicated threadpilot_test database')
    run_dir = ROOT / 'backend/runtime' / ('live-' + uuid4().hex[:12])
    run_dir.mkdir(parents=True)
    target = run_dir / 'report.json'
    settings = Settings(**{**settings.model_dump(), 'database_url': rw, 'ai_database_url': ro, 'workflow_db': run_dir / 'sql.sqlite3'})
    database = Database(settings)
    report: dict[str, Any] = {'started_at': datetime.now(timezone.utc).isoformat(), 'model': settings.openai_model,
        'api_style': settings.intent_api_style, 'business_time': NOW.isoformat(), 'database': 'isolated MySQL threadpilot_test',
        'external_delivery': 'simulated only', 'workflow': [], 'requests': [], 'sql': []}

    async def capture(response: httpx.Response) -> None:
        """场景 1.1：记录真实响应 ID 和 token 用量，不记录认证头。"""
        await response.aread()
        try:
            payload = response.json() if 'json' in response.headers.get('content-type', '') else {}
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        report['requests'].append({'status': response.status_code, 'request_id': response.headers.get('x-request-id'),
                                   'response_id': payload.get('id'), 'model': payload.get('model'), 'usage': payload.get('usage'), 'error_code': (payload.get('error') or {}).get('code'), 'retry_after': response.headers.get('retry-after')})

    print('Report:', target, flush=True)
    try:
        async with AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value(), base_url=settings.openai_base_url,
            timeout=settings.openai_timeout_seconds, max_retries=2,
            http_client=httpx.AsyncClient(event_hooks={'response': [capture]})) as client:
            classifier = IntentClassifier(client, settings.openai_model, settings.intent_api_style)
            selected = set(os.environ.get('LIVE_SCENARIOS', ','.join(SCENARIOS)).split(','))
            if not selected or selected - set(SCENARIOS):
                raise ValueError('LIVE_SCENARIOS must contain known scenario numbers')
            report['selected_scenarios'] = sorted(selected)
            for scenario, turns in SCENARIOS.items():
                if scenario not in selected:
                    continue
                engine = WorkflowEngine(DatabaseDataTools(database), WorkflowStore(run_dir / (scenario + '.sqlite3')), lambda: NOW, RecordingSender())
                state = DialogState(active_order='ORD-005' if scenario in ('1.2', '1.3', '3.2', '3.3') else None)
                engine.store.save(state)
                for row, expected, _, clarification, tool, phrase in turns:
                    raw = next(r['cells']['F'] for r in WORKBOOK if r['row'] == row)
                    message = re.sub(r'^Turn\s*\d+\s*:\s*', '', raw).split('/')[0]
                    item: dict[str, Any] = {'scenario': scenario, 'row': row, 'input': message, 'expected': expected}
                    try:
                        result = await engine.chat(ChatRequest(message=message, session_id=state.session_id), classifier)
                        state = result.state
                        item.update(actual=result.intent.value, slots=result.slots.model_dump(mode='json'), answer=result.answer,
                            checks={'intent': result.intent == expected, 'clarification': result.needs_clarification == clarification,
                                'tool': tool in [c.name for c in result.tool_calls] if tool else not result.tool_calls,
                                'constraint': phrase in result.answer})
                    except Exception as error:
                        item.update(error_type=type(error).__name__, cause_type=type(error.__cause__).__name__ if error.__cause__ else None, cause=str(error.__cause__).replace(settings.openai_api_key.get_secret_value(), '[REDACTED]')[:300] if error.__cause__ else None, checks={'completed': False})
                    report['workflow'].append(item)
                    save(target, report)
                    print(f"{scenario} row {row}: {item.get('actual', item.get('error_type'))} {item['checks']}", flush=True)
                    await asyncio.sleep(float(os.environ.get('LIVE_CALL_INTERVAL_SECONDS', '3')))

        service = AISQLService(settings)
        try:
            first = service.ask('For order ORD-005, show order_id and pieces from the current database. Return those exact columns.', None, NOW.isoformat())
            with database.sessions() as session:
                current = session.scalar(select(Order).where(Order.order_id == 'ORD-005'))
                original, record_id = current.pieces, current.id
            report['sql'].append({'case': 'initial', 'result': first,
                'passed': any(r.get('order_id') == 'ORD-005' and r.get('pieces') == original for q in first['queries'] for r in q['rows'])})
            save(target, report)
            try:
                with database.sessions.begin() as session:
                    session.get(Order, record_id).pieces = original + 7
                second = service.ask('Refresh it now. Again show order_id and pieces from the latest database.', first['session_id'], NOW.isoformat())
                report['sql'].append({'case': 'refresh_after_database_update', 'expected_pieces': original + 7, 'result': second,
                    'passed': any(r.get('order_id') == 'ORD-005' and r.get('pieces') == original + 7 for q in second['queries'] for r in q['rows'])})
            finally:
                with database.sessions.begin() as session:
                    session.get(Order, record_id).pieces = original
            save(target, report)
        finally:
            service.close()
    except Exception as error:
        report['fatal_error'] = {'type': type(error).__name__, 'status': getattr(error, 'status_code', None), 'cause_type': type(error.__cause__).__name__ if error.__cause__ else None, 'cause': str(error.__cause__).replace(settings.openai_api_key.get_secret_value(), '[REDACTED]')[:300] if error.__cause__ else None}
    finally:
        database.close()
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['summary'] = {'workflow_passed': sum(all(r['checks'].values()) for r in report['workflow']),
                             'workflow_total': len(report['workflow']), 'sql_passed': sum(r['passed'] for r in report['sql']),
                             'sql_total': len(report['sql']), 'provider_requests': len(report['requests'])}
        save(target, report)
        print(json.dumps(report['summary']), flush=True)
        print('Report:', target, flush=True)

    expected_turns = sum(len(SCENARIOS[name]) for name in report.get('selected_scenarios', []))
    if report.get('fatal_error') or report['summary']['workflow_passed'] != expected_turns or report['summary']['sql_passed'] != 2:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(evaluate())
