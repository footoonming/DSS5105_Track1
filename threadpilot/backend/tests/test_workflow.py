"""场景 1.1–3.3：来自 dialogs.xlsx 的逐轮回归及危险边界测试。"""
import asyncio
import csv
import json
import re
import shutil
import zipfile
from xml.etree import ElementTree
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from app.intent_classifier import IntentClassifier, SYSTEM_PROMPT
from app.schemas import ChatRequest, Classification, DialogState, Intent, Slots
from app.workflow_engine import WorkflowEngine
from app.workflow_store import WorkflowStore
from app.workflow_tools import DataTools

DATA = Path(__file__).resolve().parents[2] / 'data'
NOW = datetime.fromisoformat('2026-04-01T09:00:00+08:00')
WORKBOOK = json.loads((Path(__file__).parent / 'fixtures/dialogs.json').read_text(encoding='utf-8'))

# Each tuple: workbook row, expected intent, annotated extraction, clarification, required tool, reply invariant.
# The provider returns annotated JSON; these are deterministic routing/SDK tests, not a claim of live model accuracy.
SCENARIOS = {
    '1.1': [
        (2, 'order.lookup', {'customer': 'TrendCart'}, True, 'search_orders', 'Several matching'),
        (3, 'order.lookup', {'product': 'Scarf'}, False, 'refresh_order', 'ORD-005'),
        (4, 'order.lookup', {'quantity': 500, 'due_date': '2026-04-20'}, False, 'refresh_order', '2026-03-24'),
        (5, 'order.risk', {'reference': 'active'}, False, 'assess_order_risk', 'not confirmed late'),
    ],
    '1.2': [
        (6, 'order.refresh', {'reference': 'active'}, False, 'refresh_order', 'KNITTING'),
        (7, 'order.refresh', {}, False, 'refresh_order', 'no event description'),
        (8, 'order.refresh', {}, False, 'refresh_order', 'does not prove no work'),
        (9, 'order.risk', {}, False, 'assess_order_risk', 'status update'),
    ],
    '1.3': [
        (10, 'order.risk', {'reference': 'active'}, False, 'assess_order_risk', 'not confirmed late'),
        (11, 'order.risk', {'action': 'explain'}, False, 'assess_order_risk', '8 days'),
        (12, 'order.risk', {}, False, 'assess_order_risk', 'does not establish'),
        (13, 'order.risk', {'action': 'evidence'}, False, 'refresh_order', 'No per-order event history'),
    ],
    '1.4': [
        (14, 'order.compare', {'order_ids': ['ORD-005', 'ORD-021']}, True, None, 'Which aspect'),
        (15, 'order.compare', {'comparison_fields': ['due_date', 'last_activity_date']}, False, 'compare_orders', '| ORD-021 |'),
        (16, 'order.compare', {'action': 'rank'}, True, 'compare_orders', 'due-date pressure'),
        (17, 'order.compare', {'criterion': 'due_date'}, False, 'rank_comparison', 'completed orders'),
    ],
    '1.5': [
        (18, 'order.commitment', {'quantity': 800, 'product': 'hoodies', 'due_date': '25th'}, True, None, 'delivered'),
        (19, 'order.commitment', {'delivery_point': 'customer'}, False, 'estimate_capacity', 'Conditional forecast'),
        (20, 'order.commitment', {'action': 'explain'}, False, 'estimate_capacity', 'assumption'),
        (21, 'order.commitment', {'packing_loss_days': 1}, False, 'estimate_capacity', 'packing_loss_days'),
        (22, 'order.commitment', {'action': 'recommend'}, False, 'estimate_capacity', 'unconditional'),
    ],
    '1.6': [
        (23, 'order.prioritize', {}, True, None, 'next seven'),
        (24, 'order.prioritize', {'window_days': 7}, False, 'prioritize_orders', 'No opaque score'),
        (25, 'order.prioritize', {'order_ids': ['ORD-014'], 'action': 'explain'}, False, 'prioritize_orders', 'not in this exception'),
        (26, 'order.lookup', {'order_ids': ['ORD-014']}, False, 'refresh_order', 'COMPLETE'),
    ],
    '2.1': [
        (27, 'operations.normality', {'stage': 'PACKING', 'observed_output': 800}, True, None, 'same weekday'),
        (28, 'operations.normality', {'target_date': 'today', 'baseline': 'same_weekday'}, False, 'check_normality', 'same weekdays'),
        (29, 'operations.normality', {}, False, 'check_normality', 'One low observation'),
        (30, 'operations.normality', {'action': 'evidence'}, False, 'check_normality', 'production_log.csv'),
    ],
    '2.2': [
        (31, 'operations.deviation', {'stage': 'PACKING', 'target_date': 'yesterday'}, False, 'explain_deviation', 'co-occurring'),
        (32, 'operations.deviation', {}, False, 'explain_deviation', 'not proof of causation'),
        (33, 'operations.deviation', {'action': 'evidence'}, False, 'explain_deviation', 'pieces_completed'),
        (34, 'operations.deviation', {'action': 'recommend'}, False, 'explain_deviation', 'Verify upstream'),
    ],
    '3.1': [
        (35, 'order.risk', {'order_ids': ['ORD-005']}, False, 'refresh_order', 'status update'),
        (36, 'execution.chase', {'recipient': 'Maya', 'tone': 'firm but polite', 'action': 'draft'}, False, 'draft_chase', 'Unsent draft'),
        (37, 'execution.chase', {'deadline': 'tomorrow noon', 'action': 'revise'}, False, 'draft_chase', '2026-04-02T12:00:00+08:00'),
        (38, 'execution.chase', {'action': 'send'}, False, 'refresh_order', 'send now'),
        (39, 'execution.chase', {}, False, 'send_chase', 'Message sent'),
    ],
    '3.2': [
        (40, 'execution.note', {'text': 'We escalated this today.'}, True, 'refresh_order', 'correct order'),
        (41, 'execution.note', {'order_ids': ['ORD-005'], 'action': 'confirm_target'}, False, 'refresh_order', 'confirm to save'),
        (42, 'execution.note', {}, False, 'save_internal_note', 'not sent externally'),
    ],
    '3.3': [
        (43, 'execution.reminder', {'condition': 'no_reply', 'deadline': 'tomorrow noon'}, False, 'refresh_order', '2026-04-02T12:00:00+08:00'),
        (44, 'execution.reminder', {'deadline': '2 p.m.'}, False, 'refresh_order', '2026-04-02T14:00:00+08:00'),
        (45, 'execution.reminder', {}, False, 'upsert_reminder', 'only if'),
        (46, 'execution.reminder', {'deadline': 'Friday morning', 'action': 'update'}, True, 'refresh_order', 'exact time'),
    ],
}


class RecordingSender:
    def __init__(self) -> None:
        """场景 3.1：测试替身只记录调用，绝不真正发送。"""
        self.sent: list[dict[str, Any]] = []

    async def send(self, payload: dict[str, Any], idempotency_key: str) -> str:
        """场景 3.1：模拟真实发送回执并捕获幂等键。"""
        self.sent.append({'payload': payload, 'id': idempotency_key})
        return 'test-receipt'


class FixedClassifier:
    def __init__(self, intent: str, **slots: Any) -> None:
        """场景 1.1–3.3：用于独立边界测试的显式语义提取。"""
        self.result = Classification(intent=Intent(intent), slots=Slots(**slots), confidence=.99)

    async def classify(self, message: str, state: DialogState, now: datetime) -> Classification:
        """场景 1.1–3.3：返回可控提取，不模拟自然语言模型准确率。"""
        return self.result


def make_engine(tmp_path: Path) -> WorkflowEngine:
    """场景 1.1–3.3：使用正式 CSV 和隔离临时数据库。"""
    return WorkflowEngine(DataTools(DATA), WorkflowStore(tmp_path / 'workflow.sqlite3'), lambda: NOW, RecordingSender())


def provider_response(classification: Classification) -> httpx.Response:
    """场景 1.1–3.3：真实 SDK 解析协议层模拟 JSON 输出。"""
    return httpx.Response(200, json={'id': 'resp_test', 'object': 'response', 'created_at': 1,
                                   'status': 'completed', 'model': 'gpt-4.1', 'output': [
        {'type': 'message', 'id': 'msg_test', 'role': 'assistant', 'status': 'completed',
         'content': [{'type': 'output_text', 'text': classification.model_dump_json(), 'annotations': []}]}]})


@pytest.mark.parametrize('storage', ['csv', 'database'])
@pytest.mark.parametrize('scenario', SCENARIOS)
def test_workbook_multiturn_scenario(scenario: str, tmp_path: Path, storage: str, business_database) -> None:
    """场景 1.1–3.3：11 个参数化用例逐轮使用工作簿原始输入并验证路由。"""
    async def run() -> None:
        """场景 1.1–3.3：每轮断言意图、追问、工具、回复约束和写操作确认。"""
        engine = make_engine(tmp_path)
        if storage == 'database':
            from app.services.snapshot_service import DatabaseDataTools
            engine.tools = DatabaseDataTools(business_database)
        state = DialogState(active_order='ORD-005' if scenario in ('1.2', '1.3', '3.2', '3.3') else None)
        engine.store.save(state)
        for row, intent, slots, clarification, tool, phrase in SCENARIOS[scenario]:
            raw = next(r['cells']['F'] for r in WORKBOOK if r['row'] == row)
            text = re.sub(r'^Turn\s*\d+\s*:\s*', '', raw).split('/')[0]
            expected = Classification(intent=Intent(intent), slots=Slots(**slots), confidence=.99)

            def handler(request: httpx.Request) -> httpx.Response:
                """场景 1.1–3.3：验证请求确实使用独立提示词与 JSON Schema。"""
                payload = json.loads(request.content)
                assert request.url.path == '/v1/responses'
                assert payload['instructions'] == SYSTEM_PROMPT
                assert payload['text']['format']['type'] == 'json_schema'
                assert payload['store'] is False
                assert text in payload['input'][0]['content']
                return provider_response(expected)

            async with AsyncOpenAI(api_key='test', http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
                response = await engine.chat(ChatRequest(message=text, session_id=state.session_id), IntentClassifier(client))
            assert response.intent == intent, (row, response)
            assert response.needs_clarification == clarification, (row, response.answer)
            names = [call.name for call in response.tool_calls]
            assert (tool in names) if tool else not names, (row, names)
            assert phrase in response.answer, (row, response.answer)
            writes = [c for c in response.tool_calls if c.requires_confirmation]
            assert not writes or engine.confirmation_word(text)
            if response.evidence:
                assert all(e.url.endswith(f'/{e.row}') and e.record for e in response.evidence)
            state = response.state
        if scenario == '3.1':
            assert len(engine.sender.sent) == 1
            assert '2026-04-02T12:00:00+08:00' in engine.sender.sent[0]['payload']['text']
        if scenario == '3.3':
            assert engine.store.get_reminder(state.session_id, 'ORD-005', 'no_reply')['deadline'] == '2026-04-02T14:00:00+08:00'
    asyncio.run(run())


def test_refresh_and_multiple_candidates(tmp_path: Path) -> None:
    """场景 1.1/1.2：多候选不自动选取；磁盘更新后不复用旧字段。"""
    async def run() -> None:
        """场景 1.1/1.2：修改隔离 CSV 模拟生产系统刷新。"""
        directory = tmp_path / 'data'
        directory.mkdir()
        for file in DATA.glob('*.csv'):
            shutil.copy(file, directory)
        engine = make_engine(tmp_path)
        engine.tools = DataTools(directory)
        response = await engine.chat(ChatRequest(message='TrendCart order'), FixedClassifier('order.lookup', customer='TrendCart'))
        assert response.needs_clarification and response.state.active_order is None
        session = response.state.session_id
        response = await engine.chat(ChatRequest(message='ORD-005', session_id=session), FixedClassifier('order.lookup', order_ids=['ORD-005']))
        file = directory / 'orders.csv'
        rows = list(csv.DictReader(file.open(encoding='utf-8-sig')))
        for row in rows:
            if row['order_id'] == 'ORD-005':
                row['current_stage'] = 'ASSEMBLY'
                row['last_activity_date'] = '2026-04-01'
        with file.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        response = await engine.chat(ChatRequest(message='Has it moved?', session_id=session), FixedClassifier('order.refresh', reference='active'))
        assert 'ASSEMBLY' in response.answer and '2026-04-01' in response.answer
        assert response.state.active_order == 'ORD-005'
    asyncio.run(run())


def test_comparison_pronoun_and_no_fabricated_blockers(tmp_path: Path) -> None:
    """场景 1.4/2.2：比较后的 it 必须追问，解释不能虚构 blocker。"""
    async def run() -> None:
        """场景 1.4：即使模型错误偏向 active，仍由服务器阻止歧义选择。"""
        engine = make_engine(tmp_path)
        response = await engine.chat(ChatRequest(message='Compare ORD-005 and ORD-021'), FixedClassifier('order.compare', order_ids=['ORD-005', 'ORD-021'], comparison_fields=['due_date']))
        response = await engine.chat(ChatRequest(message='Chase it', session_id=response.state.session_id), FixedClassifier('execution.chase', reference='active'))
        assert response.needs_clarification and not response.tool_calls
        assert 'ORD-005' in response.answer and 'ORD-021' in response.answer
    asyncio.run(run())


def test_write_confirmation_revision_idempotency_and_restart(tmp_path: Path) -> None:
    """场景 3.2/3.3：二次确认、旧确认失效、重试去重和重启恢复。"""
    async def run() -> None:
        """场景 3.2：预览修订后不能使用旧 token 保存。"""
        engine = make_engine(tmp_path)
        response = await engine.chat(ChatRequest(message='Add internal note to ORD-005'), FixedClassifier('execution.note', order_ids=['ORD-005'], text='Escalated today.'))
        old = response.confirmation_id
        session = response.state.session_id
        assert response.confirmation_required
        assert engine.store.action_result(old, session) is None
        revised = await engine.chat(ChatRequest(message='Revise note on ORD-005', session_id=session), FixedClassifier('execution.note', order_ids=['ORD-005'], text='Escalated to manager today.'))
        failed = await engine.chat(ChatRequest(message='Save it', session_id=session, confirmation_id=old), FixedClassifier('unknown'))
        assert failed.needs_clarification and not any(c.requires_confirmation for c in failed.tool_calls)
        engine = make_engine(tmp_path)
        saved = await engine.chat(ChatRequest(message='Save it', session_id=session, confirmation_id=revised.confirmation_id), FixedClassifier('unknown'))
        assert 'Internal note saved' in saved.answer
        retry = await engine.chat(ChatRequest(message='Save it', session_id=session, confirmation_id=revised.confirmation_id), FixedClassifier('unknown'))
        assert 'no duplicate' in retry.answer
        with engine.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM actions').fetchone()[0] == 1
    asyncio.run(run())


@pytest.mark.parametrize('has_reply', [False, True])
def test_reminder_condition_and_upsert(tmp_path: Path, has_reply: bool) -> None:
    """场景 3.3：截止前不提醒、收到回复则静默、修改更新同一条、评估去重。"""
    async def run() -> None:
        """场景 3.3：完整创建、确认、更新时间并评估触发条件。"""
        engine = make_engine(tmp_path)
        response = await engine.chat(ChatRequest(message='Remind for ORD-005'), FixedClassifier('execution.reminder', order_ids=['ORD-005'], condition='no_reply', deadline='tomorrow noon'))
        session = response.state.session_id
        await engine.chat(ChatRequest(message='Confirm', session_id=session), FixedClassifier('unknown'))
        response = await engine.chat(ChatRequest(message='Move to 2pm', session_id=session), FixedClassifier('execution.reminder', deadline='2 p.m.'))
        await engine.chat(ChatRequest(message='Confirm', session_id=session), FixedClassifier('unknown'))
        with engine.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM reminders').fetchone()[0] == 1
        engine.store.evaluate_reminders(NOW, engine.tools)
        assert not engine.store.notifications(session)
        if has_reply:
            engine.store.record_reply('external-1', 'ORD-005', NOW + timedelta(hours=4))
        engine.store.evaluate_reminders(NOW + timedelta(days=2), engine.tools)
        engine.store.evaluate_reminders(NOW + timedelta(days=2), engine.tools)
        assert len(engine.store.notifications(session)) == (0 if has_reply else 1)
    asyncio.run(run())


def test_capacity_baseline_and_no_sender(tmp_path: Path) -> None:
    """场景 1.5/2.1/3.1：验证数学变化、同 weekday 及未配置发送不谎报成功。"""
    engine = make_engine(tmp_path)
    slots = Slots(product='hoodies', quantity=800, due_date='2026-04-25', delivery_point='customer')
    base, _ = engine.tools.capacity(slots, NOW)
    downside, evidence = engine.tools.capacity(slots.model_copy(update={'packing_loss_days': 1}), NOW)
    assert downside['buffer_days_remaining'] == base['buffer_days_remaining'] - 1
    assert all(e.record.get('status') != 'SUSPENDED' for e in evidence)
    data, rows = engine.tools.normality(Slots(stage='PACKING', target_date='today', observed_output=800), NOW)
    assert data['sample_count'] == 8
    assert all(datetime.fromisoformat(e.record['date']).weekday() == NOW.weekday() for e in rows)

    async def run() -> None:
        """场景 3.1：确认后没有连接器也必须保持未发送状态。"""
        engine.sender = None
        response = await engine.chat(ChatRequest(message='Draft for ORD-005'), FixedClassifier('execution.chase', order_ids=['ORD-005'], recipient='Maya', action='draft'))
        session = response.state.session_id
        await engine.chat(ChatRequest(message='Send it', session_id=session), FixedClassifier('execution.chase', action='send'))
        response = await engine.chat(ChatRequest(message='Send now', session_id=session), FixedClassifier('unknown'))
        assert 'not configured' in response.answer
        assert response.tool_calls[-1].executed is False
    asyncio.run(run())


def test_dialog_fixture_matches_original_workbook() -> None:
    """场景 1.1–3.3：核对每条原始 Turn 输入，防止测试转录与 Excel 漂移。"""
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(DATA / 'dialogs.xlsx') as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ElementTree.fromstring(archive.read('xl/sharedStrings.xml'))
            shared = [''.join(node.itertext()) for node in root.findall('x:si', ns)]
        root = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        inputs = {}
        for cell in root.findall('.//x:c', ns):
            coordinate = cell.attrib['r']
            if not re.fullmatch(r'F\d+', coordinate):
                continue
            value = cell.find('x:v', ns)
            if cell.attrib.get('t') == 's' and value is not None:
                text = shared[int(value.text)]
            elif cell.attrib.get('t') == 'inlineStr':
                text = ''.join(cell.find('x:is', ns).itertext())
            else:
                text = value.text if value is not None else ''
            if text:
                inputs[int(coordinate[1:])] = text
    expected = {row['row']: row['cells']['F'] for row in WORKBOOK if 'F' in row['cells']}
    assert inputs == expected
    assert sum(len(turns) for turns in SCENARIOS.values()) == 45


def test_ambiguous_comparative_rank_asks_criterion(tmp_path: Path) -> None:
    """场景 1.4：比较风险时即使模型标记 ambiguous，也应追问比较准则。"""
    async def run() -> None:
        """场景 1.4：复现真实模型评测发现的边界并断言正确后续。"""
        engine = make_engine(tmp_path)
        response = await engine.chat(ChatRequest(message='Compare ORD-005 and ORD-021'), FixedClassifier('order.compare', comparison_fields=['due_date']))
        session = response.state.session_id
        response = await engine.chat(ChatRequest(message='Which is more risky?', session_id=session), FixedClassifier('order.compare', action='rank', reference='ambiguous'))
        assert response.needs_clarification and 'due-date pressure' in response.answer
        response = await engine.chat(ChatRequest(message='Nearest deadline.', session_id=session), FixedClassifier('order.compare', action='rank', criterion='due_date', reference='ambiguous'))
        assert not response.needs_clarification
        assert 'Review ORD-005 first' in response.answer
    asyncio.run(run())


def test_confirmation_rejects_changed_source_and_expiry(tmp_path: Path) -> None:
    """场景 3.2：预览后原始订单改变或确认过期，不保存旧意图。"""
    async def run() -> None:
        """场景 3.2：验证两种失效都没有落地业务写操作。"""
        engine = make_engine(tmp_path)
        response = await engine.chat(ChatRequest(message='Note on ORD-005'), FixedClassifier('execution.note', text='Escalated today.'))
        session = response.state.session_id
        state = engine.store.load(session)
        state.pending_action.source_snapshot['current_stage'] = 'PACKING'
        engine.store.save(state)
        response = await engine.chat(ChatRequest(message='Save it', session_id=session), FixedClassifier('unknown'))
        assert 'record changed' in response.answer
        assert not response.confirmation_required
        await engine.chat(ChatRequest(message='Note on ORD-005', session_id=session), FixedClassifier('execution.note', text='Escalated today.'))
        engine.clock = lambda: NOW + timedelta(minutes=16)
        response = await engine.chat(ChatRequest(message='Save it', session_id=session), FixedClassifier('unknown'))
        assert 'expired' in response.answer
        with engine.store.connection() as db:
            assert db.execute('SELECT COUNT(*) FROM actions').fetchone()[0] == 0
    asyncio.run(run())


def test_unknown_delivery_retries_same_key(tmp_path: Path) -> None:
    """场景 3.1：未知送达结果不伪造成功；重试使用同一个幂等键。"""
    class UncertainSender:
        def __init__(self) -> None:
            """场景 3.1：模拟第一次超时、第二次成功的外部网关。"""
            self.keys: list[str] = []

        async def send(self, payload: dict[str, Any], idempotency_key: str) -> str:
            """场景 3.1：捕获两次请求的键，第一次制造响应不确定。"""
            self.keys.append(idempotency_key)
            if len(self.keys) == 1:
                raise httpx.ReadTimeout('Uncertain delivery')
            return 'actual-receipt'

    async def run() -> None:
        """场景 3.1：只在收到真实成功结果后清除待确认发送。"""
        engine = make_engine(tmp_path)
        sender = UncertainSender()
        engine.sender = sender
        response = await engine.chat(ChatRequest(message='Draft ORD-005'), FixedClassifier('execution.chase', recipient='Maya', action='draft'))
        session = response.state.session_id
        preview = await engine.chat(ChatRequest(message='Send it', session_id=session), FixedClassifier('execution.chase', action='send'))
        request = ChatRequest(message='Send now', session_id=session, confirmation_id=preview.confirmation_id)
        response = await engine.chat(request, FixedClassifier('unknown'))
        assert 'not confirmed' in response.answer and response.confirmation_required
        response = await engine.chat(request, FixedClassifier('unknown'))
        assert 'Message sent' in response.answer and not response.confirmation_required
        assert sender.keys == [preview.confirmation_id, preview.confirmation_id]
    asyncio.run(run())
