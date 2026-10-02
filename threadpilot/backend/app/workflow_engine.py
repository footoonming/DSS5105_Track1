"""场景 1.1–3.3：模型识别、确定性路由、状态与确认闸门。"""
import asyncio
import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

from .schemas import (ChatRequest, ChatResponse, Classification, DialogState, Evidence,
                      Intent, PendingAction, PendingClarification, Slots, ToolCall)
from .workflow_store import Sender, WorkflowStore
from .workflow_tools import DataTools, resolve_date, resolve_datetime


class Classifier(Protocol):
    async def classify(self, message: str, state: DialogState, now: datetime) -> Classification:
        """场景 1.1–3.3：允许真实 SDK 与测试替身使用同一分类接口。"""
        ...


class WorkflowEngine:
    def __init__(self, tools: DataTools, store: WorkflowStore, clock: Callable[[], datetime], sender: Sender | None = None) -> None:
        """场景 1.1–3.3：共享工具、持久化和显式业务时钟；串行保护本地状态。"""
        self.tools, self.store, self.clock, self.sender = tools, store, clock, sender
        self.lock = asyncio.Lock()

    async def chat(self, request: ChatRequest, classifier: Classifier) -> ChatResponse:
        """场景 1.1–3.3：原子处理一个本地会话轮次，客户端不能提交状态或工具。"""
        async with self.lock:
            state = self.store.load(request.session_id) if request.session_id else DialogState()
            now = self.clock()
            if request.selected_order_id and not state.active_order and not state.comparison_orders:
                state.active_order = self.tools.refresh_order(request.selected_order_id).record['order_id']
            confirmed = self.confirmation_word(request.message)
            if confirmed:
                response = await self.confirm(request, state, now)
            else:
                # Any new turn revokes the old preview, including revisions and topic changes.
                state.pending_action = None
                classification = await classifier.classify(request.message, state, now)
                response = self.route(request.message, classification, state, now)
            state.revision += 1
            state.history = (state.history + [{'role': 'user', 'content': request.message},
                                             {'role': 'assistant', 'content': response.answer}])[-16:]
            self.store.save(state)
            return response.model_copy(update={'state': state.model_copy(deep=True)})

    @staticmethod
    def confirmation_word(message: str) -> bool:
        """场景 3.1–3.3：确认只认明确命令，不信任模型生成的布尔值。"""
        return message.strip().casefold().rstrip('.!。！') in {'send now', 'save it', 'confirm', 'confirm save', 'confirm create', 'confirm update', '确认', '确认发送', '确认保存', '确认创建', '确认更新'}

    def response(self, state: DialogState, result: Classification, now: datetime, answer: str,
                 calls: list[ToolCall], evidence: list[Evidence], question: str | None = None) -> ChatResponse:
        """场景 1.1–3.3：统一返回结构和逐行证据，不让模型覆盖已计算结论。"""
        evidence = list({(e.source, e.row): e for e in evidence}.values())
        if evidence:
            answer += '\n\nSource evidence: ' + '; '.join(f'[{e.source} {"record" if e.record_id is not None else "row"} {e.row}]({e.url})' + (f' (imported from {e.original_source})' if e.original_source else '') for e in evidence[:12])
            if len(evidence) > 12:
                answer += f'. All {len(evidence)} source rows are included in the evidence field.'
        answer += f'\nAs of {now.isoformat()}; {getattr(self.tools, "freshness", "refreshed CSV test fixture")}.'
        return ChatResponse(answer=answer, intent=result.intent, slots=state.slots,
                            confidence=result.confidence, needs_clarification=bool(question), clarification_question=question,
                            confirmation_required=state.pending_action is not None,
                            confirmation_id=state.pending_action.id if state.pending_action else None,
                            state=state, tool_calls=calls, evidence=evidence,
                            order_ids=state.last_order_ids[:10], selected_order_id=state.active_order,
                            sources=list(dict.fromkeys(e.source for e in evidence)), business_date=now.date().isoformat())

    def ask(self, question: str, state: DialogState, result: Classification, now: datetime,
            calls: list[ToolCall], evidence: list[Evidence], candidates: list[str] | None = None) -> ChatResponse:
        """场景 1.1/1.4/1.5/1.6/2.1/3.1–3.3：保存缺槽问题并追问最小区分信息。"""
        state.pending_clarification = PendingClarification(intent=result.intent, question=question,
                                                        slots=state.slots, candidates=candidates or [])
        return self.response(state, result, now, question, calls, evidence, question)

    def route(self, message: str, result: Classification, state: DialogState, now: datetime) -> ChatResponse:
        """场景 1.1–3.3：合并同意图槽位，再执行服务器约束。"""
        intent = result.intent
        previous_slots = state.slots
        base = state.slots.model_dump() if state.last_intent == intent else Slots().model_dump()
        fresh = result.slots.model_dump(exclude_defaults=True)
        explicit_ids = list(dict.fromkeys(re.findall(r'\bORD-\d{3}\b', message.upper())))
        if explicit_ids:
            fresh['order_ids'] = explicit_ids
        elif 'order_ids' in fresh:
            # Model guesses are not entity resolution. Only the user's explicit IDs
            # (or previously server-resolved slots) may select an order.
            fresh.pop('order_ids')
        if intent == Intent.ORDER_LOOKUP and not explicit_ids and any(key in fresh for key in ('customer', 'product', 'quantity', 'due_date')):
            base['order_ids'] = []
        if 'order_ids' in fresh and intent not in (Intent.ORDER_COMPARE,):
            for key in ('customer', 'product', 'quantity', 'due_date'):
                base[key] = None
        base.update({k: v for k, v in fresh.items() if v is not None})
        slots = Slots.model_validate(base)
        # Read-action flags should not leak into a later command.
        slots.action = result.slots.action
        slots.reference = result.slots.reference
        state.slots = slots
        state.last_intent = intent
        state.pending_clarification = None
        calls: list[ToolCall] = []
        evidence: list[Evidence] = []
        if state.comparison_orders and not explicit_ids and intent not in (Intent.ORDER_COMPARE, Intent.ORDER_COMMITMENT, Intent.ORDER_PRIORITIZE, Intent.OPERATIONS_NORMALITY, Intent.OPERATIONS_DEVIATION):
            return self.ask('Which order do you mean: ' + ', '.join(state.comparison_orders) + '?', state, result, now, calls, evidence)
        if result.confidence < 0.65 or intent == Intent.UNKNOWN:
            return self.ask(result.clarification_question or 'Which order or operation would you like to check?', state, result, now, calls, evidence)
        comparative_ranking = intent == Intent.ORDER_COMPARE and (slots.action == 'rank' or slots.criterion is not None)
        if (slots.reference == 'ambiguous' and not comparative_ranking) or (state.comparison_orders and slots.reference == 'active' and not slots.order_ids and intent != Intent.ORDER_COMPARE):
            return self.ask('Which order do you mean: ' + ', '.join(state.comparison_orders) + '?', state, result, now, calls, evidence)
        if slots.due_date:
            try:
                slots.due_date = resolve_date(slots.due_date, now).isoformat()
            except ValueError:
                return self.ask('What is the explicit due date (YYYY-MM-DD)?', state, result, now, calls, evidence)

        if intent == Intent.ORDER_LOOKUP:
            if not any((slots.order_ids, slots.customer, slots.product, slots.quantity, slots.due_date)):
                return self.ask('Which order ID, customer or product?', state, result, now, calls, evidence)
            matches = self.tools.search_orders(slots)
            evidence.extend(matches)
            calls.append(ToolCall(name='search_orders', arguments=slots.model_dump(), result={'candidates': [e.record for e in matches]}))
            if len(matches) != 1:
                state.active_order = None
                options = '; '.join(f"{e.record['order_id']}: {e.record['product']}, {e.record['pieces']} pieces, due {e.record['due_date']}" for e in matches)
                state.last_order_ids = [e.record['order_id'] for e in matches]
                return self.ask(('Several matching orders. Which order ID, quantity or due date? ' + options) if matches else 'No matching order. Please check the order ID, quantity or due date.', state, result, now, calls, evidence, state.last_order_ids)
            order = self.select(matches[0].record['order_id'], state, calls, evidence)
            answer = self.order_facts(order)
        elif intent == Intent.ORDER_COMPARE:
            ids = slots.order_ids or state.comparison_orders
            if len(set(ids)) != 2:
                return self.ask('Which two distinct order IDs should I compare?', state, result, now, calls, evidence)
            state.comparison_orders = ids
            state.active_order = None
            state.last_order_ids = ids
            if not slots.comparison_fields:
                return self.ask('Which aspect matters: due date, stage, latest activity or status?', state, result, now, calls, evidence)
            rows = [self.tools.refresh_order(i) for i in ids]
            evidence.extend(rows)
            calls.append(ToolCall(name='compare_orders', arguments={'order_ids': ids, 'fields': slots.comparison_fields}, result={'records': [e.record for e in rows]}))
            if slots.action == 'rank' and not result.slots.criterion:
                slots.criterion = None
                return self.ask('Should I prioritise by due-date pressure or update recency?', state, result, now, calls, evidence)
            answer = '| Order | ' + ' | '.join(slots.comparison_fields) + ' |\n| --- | ' + ' | '.join('---' for _ in slots.comparison_fields) + ' |\n'
            answer += '\n'.join('| ' + e.record['order_id'] + ' | ' + ' | '.join(e.record[f] for f in slots.comparison_fields) + ' |' for e in rows)
            if slots.criterion:
                active = [e for e in rows if e.record['status'] == 'IN_PROGRESS']
                ranked = sorted(active, key=lambda e: (e.record[slots.criterion], e.record['order_id']))
                answer += '\nTransparent rule: ' + slots.criterion + ' ascending among unfinished orders; completed orders do not need a delivery chase. '
                answer += ('Review ' + ranked[0].record['order_id'] + ' first.') if ranked else 'Both orders are complete.'
                calls.append(ToolCall(name='rank_comparison', arguments={'criterion': slots.criterion}, result={'order_ids': [e.record['order_id'] for e in ranked]}))
        elif intent == Intent.ORDER_PRIORITIZE:
            if slots.window_days is None:
                return self.ask('Due today only, or include the next seven days? Overdue active orders will be included.', state, result, now, calls, evidence)
            data, rows = self.tools.prioritize(slots, now)
            evidence.extend(rows)
            calls.append(ToolCall(name='prioritize_orders', arguments={'window_days': slots.window_days, 'customer': slots.customer}, result=data))
            state.last_order_ids = [e.record['order_id'] for e in rows]
            answer = data['rule'] + '\n' + '\n'.join(f"{i}. {e.record['order_id']}: due {e.record['due_date']}, last activity {e.record['last_activity_date']}." for i, e in enumerate(rows, 1))
            if slots.order_ids:
                requested = slots.order_ids[0]
                position = state.last_order_ids.index(requested) + 1 if requested in state.last_order_ids else None
                answer += f'\n{requested}: actual rank {position}; ' if position else f'\n{requested} is not in this exception list. '
                inspected = self.tools.refresh_order(requested)
                evidence.append(inspected)
                calls.append(ToolCall(name='refresh_order', arguments={'order_id': requested}, result=inspected.record))
                answer += self.order_facts(inspected)
            answer += '\nRanking indicates review urgency, not a prediction of failure. Select an order ID to drill down.'
        elif intent == Intent.ORDER_COMMITMENT:
            if not slots.delivery_point:
                return self.ask('Does the deadline mean ready at our factory or delivered to the customer?', state, result, now, calls, evidence)
            if not slots.quantity or not slots.product or not slots.due_date:
                return self.ask('What product, quantity and explicit due date should I estimate?', state, result, now, calls, evidence)
            if resolve_date(slots.due_date, now) <= now.date():
                return self.ask('That date is not in the future. What new delivery date should I assess?', state, result, now, calls, evidence)
            data, rows = self.tools.capacity(slots, now)
            evidence.extend(rows)
            calls.append(ToolCall(name='estimate_capacity', arguments=slots.model_dump(), result=data))
            answer = 'Conditional forecast, not a promise:\n' + json.dumps(data, ensure_ascii=False, indent=2)
        elif intent in (Intent.OPERATIONS_NORMALITY, Intent.OPERATIONS_DEVIATION):
            if not slots.stage or not slots.target_date or (intent == Intent.OPERATIONS_NORMALITY and not slots.baseline):
                return self.ask('Which stage and date? Do you mean today, compared with the same weekday in recent working weeks?', state, result, now, calls, evidence)
            try:
                slots.target_date = resolve_date(slots.target_date, now).isoformat()
            except ValueError:
                return self.ask('What is the explicit observation date?', state, result, now, calls, evidence)
            function = self.tools.normality if intent == Intent.OPERATIONS_NORMALITY else self.tools.deviation
            data, rows = function(slots, now)
            evidence.extend(rows)
            calls.append(ToolCall(name='check_normality' if intent == Intent.OPERATIONS_NORMALITY else 'explain_deviation', arguments=slots.model_dump(), result=data))
            answer = 'Recorded facts and labelled interpretation:\n' + json.dumps(data, ensure_ascii=False, indent=2)
        else:
            ids = slots.order_ids
            if len(ids) > 1:
                return self.ask('Which single order should I use?', state, result, now, calls, evidence)
            order_id = ids[0] if ids else state.active_order
            if not order_id:
                return self.ask('Which order should I use? Please give its ID or customer.', state, result, now, calls, evidence)
            order = self.select(order_id, state, calls, evidence)
            if intent == Intent.ORDER_REFRESH:
                answer = self.order_facts(order) + '\nOnly last_activity_date is recorded; no event description is available. An unchanged record does not prove no work happened.'
                answer += ('\nThe last recorded activity date is today; author and time are not available.'
                           if order.record['last_activity_date'] == now.date().isoformat()
                           else f'\nNo update dated {now.date().isoformat()} is recorded.')
            elif intent == Intent.ORDER_RISK:
                risk = self.tools.assess_risk(order, now)
                calls.append(ToolCall(name='assess_order_risk', arguments={'order_id': order_id}, result=risk))
                answer = self.order_facts(order) + '\nFacts and risk interpretation:\n' + json.dumps(risk, indent=2)
                answer += '\nA risk pattern does not establish that it will be late. Request a status update if needed.'
            else:
                return self.execution(message, result, state, now, calls, evidence, order, previous_slots)
        return self.response(state, result, now, answer, calls, evidence)

    def select(self, order_id: str, state: DialogState, calls: list[ToolCall], evidence: list[Evidence]) -> Evidence:
        """场景 1.1/1.2：唯一识别后刷新字段，保存 active_order 和客户。"""
        order = self.tools.refresh_order(order_id)
        calls.append(ToolCall(name='refresh_order', arguments={'order_id': order_id}, result=order.record))
        evidence.append(order)
        state.active_order = order_id
        state.active_customer = order.record['customer']
        state.comparison_orders = []
        state.last_order_ids = [order_id]
        return order

    @staticmethod
    def order_facts(order: Evidence) -> str:
        """场景 1.1–1.4：只展示正式订单记录，不生成虚构活动描述。"""
        row = order.record
        return (f"{row['order_id']} — {row['customer']}, {row['pieces']} {row['product']}; "
                f"status {row['status']}, stage {row['current_stage']}, due {row['due_date']}, "
                f"last recorded activity {row['last_activity_date']}." +
                (f" Completed {row['completed_date']}; recorded days late: {row['days_late']}." if row['status'] == 'COMPLETE' else ''))

    def propose(self, kind: Literal['send', 'note', 'reminder'], order_id: str, payload: dict[str, Any], preview: str,
                state: DialogState, now: datetime) -> None:
        """场景 3.1–3.3：每次预览生成新确认键，把动作、订单和最终内容绑定。"""
        state.pending_action = PendingAction(kind=kind, order_id=order_id, payload=payload, preview=preview,
                                             created_at=now, source_snapshot=self.tools.refresh_order(order_id).record)

    def execution(self, message: str, result: Classification, state: DialogState, now: datetime,
                  calls: list[ToolCall], evidence: list[Evidence], order: Evidence, previous_slots: Slots) -> ChatResponse:
        """场景 3.1–3.3：草稿修订、内部备注预览和可更新条件提醒。"""
        slots, order_id = state.slots, order.record['order_id']
        if result.intent == Intent.EXECUTION_CHASE:
            if slots.action == 'send':
                if not state.draft or state.draft['order_id'] != order_id:
                    return self.ask('Please draft the message and specify its recipient first.', state, result, now, calls, evidence)
                preview = f"Ready to send to {state.draft['recipient']} about {order_id}:\n{state.draft['text']}\nPlease confirm 'send now'."
                self.propose('send', order_id, state.draft.copy(), preview, state, now)
                return self.response(state, result, now, preview, calls, evidence)
            recipient = slots.recipient or (state.draft or {}).get('recipient')
            if not recipient:
                return self.ask('Who should receive the draft, and what tone should I use?', state, result, now, calls, evidence)
            text = (state.draft or {}).get('text') if slots.action == 'revise' and (state.draft or {}).get('order_id') == order_id else None
            text = slots.text or text or f'Please provide an updated status, recovery plan and expected completion date for {order_id}. Please treat this as a priority. Thank you.'
            if slots.deadline:
                deadline = resolve_datetime(slots.deadline, now)
                if deadline is None:
                    return self.ask('What exact response date and time should the draft use?', state, result, now, calls, evidence)
                text = re.sub(r'\nPlease respond by .*', '', text) + f'\nPlease respond by {deadline.isoformat()}.'
            state.draft = {'order_id': order_id, 'recipient': recipient, 'text': text, 'tone': slots.tone or 'firm but polite'}
            calls.append(ToolCall(name='draft_chase', arguments={'order_id': order_id}, result=state.draft))
            answer = f"Unsent draft to {recipient} ({state.draft['tone']}):\n{text}\nDraft only; nothing has been sent."
        elif result.intent == Intent.EXECUTION_NOTE:
            if not slots.text:
                return self.ask('What exact internal note should I attach?', state, result, now, calls, evidence)
            target_is_explicit = order_id in message.upper()
            target_is_confirmed = slots.action == 'confirm_target' and bool(re.match(r'^(yes\b|是|对)', message.strip(), re.IGNORECASE))
            if not target_is_explicit and not target_is_confirmed:
                return self.ask(f'Internal note target is {order_id}. Is that the correct order?', state, result, now, calls, evidence)
            preview = f'Internal note for {order_id}, business date {now.date()}:\n{slots.text}\nPlease confirm to save. It will not be sent externally.'
            self.propose('note', order_id, {'text': slots.text, 'visibility': 'internal'}, preview, state, now)
            answer = preview
        elif result.intent == Intent.EXECUTION_REMINDER:
            if not slots.condition:
                return self.ask('Should I remind you only if no reply or no new activity is recorded?', state, result, now, calls, evidence)
            existing = self.store.get_reminder(state.session_id, order_id, slots.condition)
            prior_text = previous_slots.deadline or ''
            previous = resolve_datetime(prior_text, now) or resolve_datetime(prior_text.replace('morning', 'noon'), now)
            if existing and not previous:
                previous = datetime.fromisoformat(existing['deadline'])
            deadline = resolve_datetime(slots.deadline or '', now, previous)
            if deadline is None:
                return self.ask('What exact time on that date (for example Friday at 9 a.m.) should I check?', state, result, now, calls, evidence)
            if deadline <= now:
                return self.ask('The reminder time must be in the future. What date and time?', state, result, now, calls, evidence)
            slots.deadline = deadline.isoformat()
            preview = f"{'Update existing' if existing else 'Create'} reminder for {order_id} at {deadline.isoformat()}: notify only if {slots.condition} is still unmet in recorded data. Please confirm."
            self.propose('reminder', order_id, {'condition': slots.condition, 'deadline': deadline.isoformat(),
                         'since': existing['since'] if existing else now.isoformat()}, preview, state, now)
            answer = preview
        else:
            return self.ask('Please clarify the requested action.', state, result, now, calls, evidence)
        return self.response(state, result, now, answer, calls, evidence)

    async def confirm(self, request: ChatRequest, state: DialogState, now: datetime) -> ChatResponse:
        """场景 3.1–3.3：确认门禁、过期检测、状态刷新与真实执行结果。"""
        result = Classification(intent=state.last_intent or Intent.UNKNOWN, slots=state.slots, confidence=1)
        action = state.pending_action
        calls: list[ToolCall] = []
        evidence: list[Evidence] = []
        if request.confirmation_id:
            prior = self.store.action_result(request.confirmation_id, state.session_id)
            if prior and prior['status'] in ('saved', 'sent'):
                return self.response(state, result, now, f"Already recorded: {prior['kind']} {prior['status']}; no duplicate action.", calls, evidence)
        if not action or (request.confirmation_id and request.confirmation_id != action.id):
            return self.ask('No matching pending action. Request a new preview before confirming.', state, result, now, calls, evidence)
        if now - action.created_at > timedelta(minutes=15):
            state.pending_action = None
            return self.ask('The preview expired. Please request a fresh preview.', state, result, now, calls, evidence)
        command = request.message.casefold()
        if ('send' in command or '发送' in command) and action.kind != 'send' or ('save' in command or '保存' in command) and action.kind != 'note':
            return self.ask('That confirmation does not match the previewed action.', state, result, now, calls, evidence)
        if request.selected_order_id and request.selected_order_id != action.order_id:
            return self.ask('The selected order changed. Request a new preview for the intended order.', state, result, now, calls, evidence)
        refreshed = self.tools.refresh_order(action.order_id)
        evidence.append(refreshed)
        calls.append(ToolCall(name='refresh_order', arguments={'order_id': action.order_id}, result=refreshed.record))
        if action.source_snapshot and refreshed.record != action.source_snapshot:
            state.pending_action = None
            return self.ask('The order record changed after the preview. Review the fresh record and request a new preview.', state, result, now, calls, evidence)
        if action.kind == 'reminder' and datetime.fromisoformat(action.payload['deadline']) <= now:
            state.pending_action = None
            return self.ask('The reminder deadline passed before confirmation. Please choose a future time.', state, result, now, calls, evidence)
        outcome = await self.store.send(action, state.session_id, now, self.sender) if action.kind == 'send' else self.store.commit_local(action, state.session_id, now)
        calls.append(ToolCall(name={'send': 'send_chase', 'note': 'save_internal_note', 'reminder': 'upsert_reminder'}[action.kind],
                              arguments={'action_id': action.id, 'order_id': action.order_id, **action.payload},
                              result=outcome, requires_confirmation=True, executed=outcome['status'] != 'not_sent'))
        if outcome['status'] in ('sent', 'saved'):
            answer = {'send': 'Message sent; recipient, final text, send time and receipt recorded.',
                      'note': f'Internal note saved to {action.order_id} with timestamp. It was not sent externally.',
                      'reminder': 'Reminder created or updated in place. It will notify only if the condition remains unmet.'}[action.kind]
            state.pending_action = None
        else:
            answer = outcome['reason']
        return self.response(state, result, now, answer, calls, evidence)
