"""场景 1.1–3.3：可选真实 ChatGPT 逐轮评测；不连接实际发送服务。"""
import asyncio
import json
import os
import re
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.intent_classifier import IntentClassifier
from app.schemas import ChatRequest, DialogState
from tests.test_workflow import NOW, SCENARIOS, WORKBOOK, make_engine


async def evaluate() -> None:
    """场景 1.1–3.3：完整上下文执行 45 轮，输出实际意图与行为断言结果。"""
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    report = []
    target = Path(__file__).resolve().parents[1] / 'runtime' / 'live-evaluation.json'
    target.parent.mkdir(exist_ok=True)
    async with AsyncOpenAI(timeout=60, max_retries=2) as client:
        classifier = IntentClassifier(client, os.getenv('OPENAI_MODEL', 'gpt-4.1'))
        for scenario, turns in SCENARIOS.items():
            with tempfile.TemporaryDirectory() as temporary:
                engine = make_engine(Path(temporary))
                state = DialogState(active_order='ORD-005' if scenario in ('1.2', '1.3', '3.2', '3.3') else None)
                engine.store.save(state)
                for row, expected, _, clarification, tool, phrase in turns:
                    raw = next(r['cells']['F'] for r in WORKBOOK if r['row'] == row)
                    text = re.sub(r'^Turn\s*\d+\s*:\s*', '', raw).split('/')[0]
                    result = await engine.chat(ChatRequest(message=text, session_id=state.session_id), classifier)
                    state = result.state
                    checks = {'intent': result.intent == expected, 'clarification': result.needs_clarification == clarification,
                              'tool': tool in [c.name for c in result.tool_calls] if tool else not result.tool_calls,
                              'constraint': phrase in result.answer}
                    item = {'scenario': scenario, 'row': row, 'input': text, 'expected': expected,
                            'actual': result.intent, 'checks': checks, 'slots': result.slots.model_dump(), 'answer': result.answer}
                    report.append(item)
                    target.write_text(json.dumps({'business_now': NOW.isoformat(), 'results': report}, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(f'{scenario} row {row}: {result.intent} {checks}', flush=True)
                    if not all(checks.values()):
                        print(result.model_dump_json()[:2500], flush=True)
                    await asyncio.sleep(2)
    passed = sum(all(r['checks'].values()) for r in report)
    print(f'{passed}/{len(report)} turns passed. Report: {target}')


if __name__ == '__main__':
    asyncio.run(evaluate())
