"""Checks for the dashboard panels: settings, stage targets, the at-risk split, memos, and the follow-up panel.
They run the real page in a headless browser (see conftest.py). Settings and memos live in the browser's localStorage,
so each test starts by clearing it.
"""
from datetime import date

from dashboard_helpers import order, reset_browser_state


# =====================================================================================================================
# Settings, at-risk split, memos and the follow-up panel
# =====================================================================================================================
def test_at_risk_card_is_split_into_overdue_and_approaching(page, B):
    reset_browser_state(page)
    page.evaluate("go(8)")
    heads = page.locator("#riskCard .rk-col h3").all_inner_texts()
    sc = B[8]["status_counts"]
    assert heads[0].startswith("Already overdue") and heads[0].endswith(str(sc["late"]))
    assert heads[1].startswith("Approaching due date") and heads[1].endswith(str(sc["at_risk"]))
    assert page.locator("#riskCard .rk-col").nth(0).locator(".rk-item").count() == min(5, sc["late"])


def test_text_size_and_typeface_apply_and_persist(page):
    reset_browser_state(page)
    page.click("#settingsBtn")
    page.click('[data-tp-size="XL"]')
    page.click('[data-tp-font="serif"]')
    assert page.evaluate("document.documentElement.style.getPropertyValue('--z')") == "1.3"
    assert "Georgia" in page.evaluate("document.documentElement.style.getPropertyValue('--font')")
    page.click("#stDone")
    page.reload()
    page.wait_for_selector("#riskCard .rk-col")
    assert page.evaluate("document.documentElement.style.getPropertyValue('--z')") == "1.3"       # survived a reload
    assert page.evaluate("getComputedStyle(document.body).fontFamily").lower().startswith("georgia")
    reset_browser_state(page)


def test_stage_target_is_flagged_after_three_missed_days_only(page, B):
    reset_browser_state(page)
    page.evaluate("go(8)")
    page.click("#settingsBtn")
    page.fill('[data-tp-target="PACKING"]', "99999")
    page.fill('[data-tp-target="KNITTING"]', "1")
    page.click("#stDone")
    strip = page.inner_text("#targetStrip")
    streak = sum(1 for h in B[8]["stages"]["PACKING"]["history"] if h["value"] is not None)   # every day is below 99,999
    assert f"Packing 99,999/day · {B[8]['stages']['PACKING']['history'][-1]['value']:,} · missed {streak} days in a row" in strip
    assert "Knitting 1/day" in strip and "met yesterday" in strip
    assert "Packing below its 99,999 target" in page.inner_text("#changes")
    # one good day breaks the streak: a target the last day just meets must not say 'in a row'
    last = B[8]["stages"]["PACKING"]["history"][-1]["value"]
    page.click("#settingsBtn")
    page.fill('[data-tp-target="PACKING"]', str(last))
    page.click("#stDone")
    assert "met yesterday" in page.inner_text("#targetStrip") and "in a row" not in page.inner_text("#targetStrip")
    reset_browser_state(page)


def test_memo_records_an_amended_date_and_marks_the_order(page, B):
    reset_browser_state(page)
    page.evaluate("go(8)")
    o = order(B, 8, "ORD-120")
    page.click('[data-tp-open="memo"]')
    page.select_option("#mmOrder", "ORD-120")
    page.fill("#mmDate", "2026-04-30")
    page.fill("#mmReason", "Customer agreed after trim delay")
    page.click("#mmSave")
    row = page.locator("#memoCard tbody tr").first.inner_text()
    assert "ORD-120" in row and "Customer agreed after trim delay" in row and "30 Apr" in row
    assert f"+{(date(2026, 4, 30) - date.fromisoformat(o['due_date'])).days} days" in row
    page.fill("#q", "ORD-120")
    assert "amended: 30 Apr" in page.inner_text("#orders")
    assert "delivery date amended for ORD-120" in page.inner_text("#log")
    page.reload()
    page.wait_for_selector("#riskCard .rk-col")
    assert "ORD-120" in page.inner_text("#memoCard")            # memos survive a reload
    page.click("[data-tp-rm]")
    assert "No amended delivery dates" in page.inner_text("#memoCard")
    reset_browser_state(page)


def test_memo_for_a_specification_lands_in_its_own_table(page):
    reset_browser_state(page)
    page.evaluate("go(8)")
    page.click('[data-tp-open="memo"]')
    page.select_option("#mmOrder", "ORD-020")
    page.select_option("#mmType", "spec")
    page.fill("#mmSpec", "Switch to navy trim")
    page.click("#mmSave")
    tables = page.locator("#memoCard table")
    assert "Switch to navy trim" in tables.nth(1).inner_text() and "ORD-020" not in tables.nth(0).inner_text()
    reset_browser_state(page)


def test_follow_up_panel_shows_advice_and_drafts(page, B):
    reset_browser_state(page)
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.evaluate("go(8)")
    page.click('[data-tp-actions="ORD-120"]')
    assert page.is_visible("#actionPanel")
    body = page.inner_text("#apBody")
    e = order(B, 8, "ORD-120")["expedite"]
    assert e["label"] in body and "ORD-120" in page.input_value("#apSubject")
    assert "ORD-120" in page.input_value("#apTeams") and "ORD-120" in page.input_value("#apBodyText")
    page.click('[data-tp-copy="teams"]')
    page.wait_for_function("document.querySelector('#log').innerText.includes('Teams message draft copied for ORD-120')")
    page.keyboard.press("Escape")
    assert not page.is_visible("#actionPanel")


def test_chat_chip_opens_the_follow_up_panel(page):
    reset_browser_state(page)
    page.evaluate("go(8)")
    page.click("#chatFab")
    page.fill("#chatInput", "Should we expedite ORD-120?")
    page.press("#chatInput", "Enter")
    page.wait_for_selector('.chip[data-q="__panel:ORD-120"]')
    page.click('.chip[data-q="__panel:ORD-120"]')
    assert page.is_visible("#actionPanel") and not page.is_visible("#chatPanel")
    page.keyboard.press("Escape")


def test_use_usual_output_fills_the_targets_and_clear_empties_them(page, B):
    reset_browser_state(page)
    page.evaluate("go(8)")
    page.click("#settingsBtn")
    page.click("[data-tp-fill]")
    vals = [page.input_value(f'[data-tp-target="{s}"]') for s in ("KNITTING", "ASSEMBLY", "WASHING", "PACKING")]
    usual = [round(B[8]["stages"][s]["yesterday"]["mean"] / 10) * 10 for s in ("KNITTING", "ASSEMBLY", "WASHING", "PACKING")]
    assert vals == [str(v) for v in usual]
    page.click("[data-tp-clear]")
    assert all(page.input_value(f'[data-tp-target="{s}"]') == "" for s in ("KNITTING", "ASSEMBLY", "WASHING", "PACKING"))
    page.click("#stDone")
    reset_browser_state(page)


def test_mailto_link_keeps_the_address_readable_and_encodes_the_message(page):
    url = page.evaluate("""TPPanels.mailtoUrl("planner@example.com, boss@example.com", "Expedite request: ORD-120 (TrendCart)", "Line one\\nLine two & three")""")
    assert url == ("mailto:planner@example.com,boss@example.com?subject=Expedite%20request%3A%20ORD-120%20(TrendCart)"
                   "&body=Line%20one%0ALine%20two%20%26%20three")


def test_open_in_email_app_is_logged(page):
    reset_browser_state(page)
    page.evaluate("go(8)")
    page.click('[data-tp-actions="ORD-120"]')
    page.fill("#apTo", "planner@example.com")
    page.click("[data-tp-mail]")
    page.wait_for_function("document.querySelector('#log').innerText.includes('Email draft opened for ORD-120')")
    reset_browser_state(page)


def test_typing_a_target_does_not_pile_up_alert_pills(page):
    reset_browser_state(page)
    page.evaluate("go(8)")
    page.click("#settingsBtn")
    page.type('[data-tp-target="PACKING"]', "99999")          # five keystrokes, five input events
    page.click("#stDone")
    assert page.locator("#changes [data-tp-pill]").count() == 1
    reset_browser_state(page)


def test_dialogs_take_keyboard_focus_and_give_it_back(page):
    reset_browser_state(page)
    page.focus("#settingsBtn")
    page.keyboard.press("Enter")
    assert page.evaluate("document.querySelector('#settingsModal').contains(document.activeElement)")
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.id") == "settingsBtn"
    page.evaluate("go(8)")
    page.focus('[data-tp-actions="ORD-120"]')
    page.keyboard.press("Enter")
    assert page.evaluate("document.querySelector('#actionPanel').contains(document.activeElement)")
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.dataset.tpActions") == "ORD-120"


def test_order_ids_are_escaped_in_the_orders_table(page):
    reset_browser_state(page)
    page.evaluate("""() => { const o = B[idx].orders[0]; o.__orig = o.order_id; o.order_id = '<img src=x onerror="window.__xss=1">'; orders(); }""")
    assert page.evaluate("window.__xss") is None and "&lt;img" in page.inner_html("#orders")
    page.evaluate("() => { const o = B[idx].orders[0]; o.order_id = o.__orig; orders(); }")
