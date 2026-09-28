"""Offline contracts for a dynamic operation/target policy. No paid APIs."""

import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import model
from jev_ultrafast.browser import StalePage, browser_operation, fingerprint


@pytest.mark.parametrize("external_name", [None, "already_set"])
def test_env_loads_before_browser_harness_import(tmp_path, external_name):
    (tmp_path / ".env").write_text(
        "BU_NAME=from_file\nTYPESAFE_DEMO_PORT=8877\nTEXT_MODEL='from-file-model'\n", encoding="utf-8"
    )
    environment = os.environ.copy()
    environment.pop("BU_NAME", None)
    environment.pop("TYPESAFE_DEMO_PORT", None)
    environment.pop("TEXT_MODEL", None)
    if external_name:
        environment["BU_NAME"] = external_name
    script = (
        "import json, os; "
        "from jev_ultrafast import demo; "
        "from browser_harness import admin, helpers; "
        "print(json.dumps([admin.NAME, helpers.NAME, demo.PORT, os.environ['TEXT_MODEL']]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=environment,
        capture_output=True, text=True, check=True,
    )
    expected_name = external_name or "from_file"
    assert json.loads(result.stdout) == [expected_name, expected_name, 8877, "from-file-model"]


def page():
    state = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def choice(ids, selected):
    return {"choice": selected, "confidence": 1.0, "probabilities": {i: float(i == selected) for i in ids}}


def decision(action="e1"):
    return {
        "choice": action,
        "operation": "TYPE_TEXT",
        "target": "1",
        "confidence": 1.0,
        "probabilities": {action: 1.0},
        "latency_ms": 10,
        "usage": {},
    }


@pytest.mark.parametrize("mutation", ["unknown", "nan", "missing", "negative", "non_max", "confidence"])
def test_invalid_choice_is_rejected(mutation):
    a = choice(["a", "b"], "a")
    if mutation == "unknown":
        a["choice"] = "invented"
    elif mutation == "nan":
        a["probabilities"]["a"] = float("nan")
    elif mutation == "missing":
        del a["probabilities"]["b"]
    elif mutation == "negative":
        a["probabilities"]["b"] = -1
    elif mutation == "non_max":
        a["choice"] = "b"
    else:
        a["confidence"] = 5
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.validate_choice(a, {"a", "b"})


def test_one_index_per_node_with_operation_specific_targets():
    elements, targets, controls = model.action_space(page()["actions"])
    assert len(elements) == 2
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK"]
    assert targets["TYPE_TEXT"]["1"]["id"] == "e1"
    assert targets["CLICK"]["1"]["id"] == "e2"
    assert targets["CLICK"]["2"]["id"] == "e3"
    assert "WAIT" in controls


def test_all_heads_are_one_request_and_only_matching_head_executes(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
                "click_target": {"choice": "invented"},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    assert len(calls) == 1
    assert d["operation"] == "TYPE_TEXT" and d["target"] == "1" and d["choice"] == "e1"
    assert set(calls[0]["questions"]) == {"operation", "click_target", "type_text_target"}


def test_click_cannot_consume_a_text_target(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "type_text_target": choice(["1"], "1"),
                "click_target": choice(["1", "2", "999"], "999"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.choose(page(), "Find a book", [])


def test_target_head_receives_control_state_and_full_next_step_rules(monkeypatch):
    p = page()
    p["actions"].insert(0, {
        "id": "toggle", "kind": "click", "label": "Free cancellation", "node": 30,
        "role": "checkbox", "checked": "true", "selected": False,
    })

    def post(_url, _key, body):
        questions = body["questions"]
        target = questions["click_target"]
        assert target["criteria"]["1"]["checked"] == "true"
        assert target["criteria"]["1"]["selected"] is False
        assert questions["operation"]["instructions"]["rules"] in target["instructions"]["rules"]
        return {
            "model": "test",
            "answers": {
                "operation": choice(questions["operation"]["criteria"], "CLICK"),
                "click_target": choice(target["criteria"], "3"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(p, "Search with free cancellation", [])
    assert d["choice"] == "e3"


def test_quoted_task_text_still_uses_the_llm(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    context = model.field_context('Fly from "Zurich" to London', page()["actions"][0], page(), [])
    assert model.field_text(context)[0] == "Zurich"
    assert post.call_count == 1
    sent = json.loads(post.call_args.args[2]["messages"][1]["content"])
    assert sent["goal"] == 'Fly from "Zurich" to London'


def test_missing_text_credential_stops_before_guessing(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TEXT_MODEL_API_KEY"):
        model.field_text({"goal": 'Enter "Zurich"'})


@pytest.fixture
def runner():
    a = loop.Agent.__new__(loop.Agent)
    a.screenshots = False
    a.pending_text = None
    p = page()
    a.state = {
        "browser": Mock(fresh=Mock(return_value=True), observe=Mock(return_value=p)),
        "page": p,
        "decision": decision(),
        "goal": "Find a book",
        "history": [],
        "decisions": [],
        "status": "predicted",
        "started_at": time.perf_counter(),
        "record": False,
        "text_calls": [],
    }
    return a


def test_stale_decision_is_consumed_before_any_mutation(runner):
    runner.state["browser"].fresh.return_value = False
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["decision"] is None


def test_text_generation_checks_the_observed_page(runner, monkeypatch):
    runner.state["browser"].fresh.side_effect = lambda _page, action=None: action is None
    monkeypatch.setattr(loop, "field_text", Mock(return_value=("book", {"model": "test", "latency_ms": 10})))
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].fresh.assert_called_once_with(runner.state["page"])
    runner.state["browser"].act.assert_called_once()


def test_fill_freshness_rejects_changed_page_text(monkeypatch):
    import jev_ultrafast.browser as browser

    observed = {"page_key": ["unchanged form"], "guards": {"10": ["unchanged field"]}, "marker": ["old text"]}
    candidate = browser.Browser.__new__(browser.Browser)
    evaluate = Mock(return_value=["new text"])
    monkeypatch.setattr(candidate, "evaluate", evaluate)
    assert not candidate.fresh(observed, {"kind": "fill", "node": 10})
    assert evaluate.call_count == 1
    assert evaluate.call_args.args[0] == browser.MARKER


def test_generated_text_reused_only_for_identical_retry_context(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 1
    assert runner.state["browser"].act.call_count == 2  # The first call rejects before any browser input.
    assert runner.pending_text is None


def test_changed_field_context_does_not_reuse_generated_text(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["page"]["text"] = "Different page context"
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 2


def test_loading_waits_do_not_trigger_no_progress_stop(runner):
    for _ in range(5):
        runner.state["decision"] = decision("wait")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert len(runner.state["history"]) == 5 and runner.state["status"] == "ready"


def test_stale_observation_preserves_executed_action(runner):
    runner.state["decision"] = decision("e3")
    runner.state["browser"].observe.side_effect = StalePage("changed")
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["action"] == "Go"
    runner.state["browser"].act.assert_called_once()


def test_observation_is_one_atomic_browser_read(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    cdp = Mock(return_value={"result": {"value": p}})
    monkeypatch.setattr(browser, "cdp", cdp)
    actual = browser_operation({"operation": "observe", "session": "test", "screenshot": False})
    assert actual["actions"] == p["actions"]
    assert cdp.call_count == 1
    assert cdp.call_args.args[0] == "Runtime.evaluate"


def test_windows_demo_starts_an_isolated_chrome(monkeypatch, tmp_path):
    from jev_ultrafast import demo

    monkeypatch.delenv("JEV_BROWSER_MODE", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(demo, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(demo.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    chrome = tmp_path / "chrome.exe"
    chrome.touch()
    monkeypatch.setenv("BH_CHROME_PATH", str(chrome))
    active = tmp_path / "artifacts" / "chrome-demo" / "DevToolsActivePort"
    active.parent.mkdir(parents=True)
    active.write_text("9333\n/devtools/browser/test\n", encoding="utf-8")
    process = Mock()
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    monkeypatch.setattr(demo.subprocess, "Popen", spawn)
    monkeypatch.setattr(demo, "daemon_alive", lambda: False)
    monkeypatch.setattr(
        demo, "urlopen",
        lambda *_args, **_kwargs: BytesIO(b'{"webSocketDebuggerUrl":"ws://127.0.0.1:9333/devtools/browser/test"}'),
    )

    assert demo.start_demo_chrome() is process
    assert os.environ["BU_CDP_URL"] == "http://127.0.0.1:9333"
    assert os.environ["JEV_DEDICATED_CHROME"] == "1"
    assert "--headless=new" in spawn.call_args.args[0]
    assert f"--user-data-dir={active.parent}" in spawn.call_args.args[0]


def test_windows_demo_reuses_a_healthy_browser_daemon(monkeypatch):
    from jev_ultrafast import demo

    monkeypatch.delenv("JEV_BROWSER_MODE", raising=False)
    monkeypatch.setattr(demo, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    monkeypatch.delenv("JEV_DEDICATED_CHROME", raising=False)
    monkeypatch.setattr(demo, "daemon_alive", lambda: True)
    probe = Mock(side_effect=[{"targetInfos": []}, {"userAgent": "HeadlessChrome/153.0"}])
    monkeypatch.setattr(demo, "cdp", probe)
    spawn = Mock()
    monkeypatch.setattr(demo.subprocess, "Popen", spawn)
    assert demo.start_demo_chrome() is None
    assert [call.args[0] for call in probe.call_args_list] == ["Target.getTargets", "Browser.getVersion"]
    assert os.environ["JEV_DEDICATED_CHROME"] == "1"
    spawn.assert_not_called()


def test_personal_mode_never_starts_an_isolated_chrome(monkeypatch):
    from jev_ultrafast import demo

    monkeypatch.setenv("JEV_BROWSER_MODE", "personal")
    spawn = Mock()
    monkeypatch.setattr(demo.subprocess, "Popen", spawn)
    assert demo.start_demo_chrome() is None
    spawn.assert_not_called()


def test_personal_mode_uses_local_chrome_discovery(monkeypatch, tmp_path):
    from jev_ultrafast import demo

    monkeypatch.setattr(demo, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    active = tmp_path / "Google" / "Chrome" / "User Data" / "DevToolsActivePort"
    active.parent.mkdir(parents=True)
    active.write_text("9333\n/devtools/browser/visible\n", encoding="utf-8")
    demo.require_personal_chrome()
    assert "BU_CDP_WS" not in os.environ
    assert "BU_CDP_URL" not in os.environ


def test_personal_mode_requires_chrome_debugging_permission(monkeypatch, tmp_path):
    from jev_ultrafast import demo

    monkeypatch.setattr(demo, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    with pytest.raises(RuntimeError, match="chrome://inspect/#remote-debugging"):
        demo.require_personal_chrome()
    assert "BU_CDP_WS" not in os.environ


@pytest.mark.parametrize("variable", ["BU_CDP_WS", "BU_CDP_URL"])
def test_personal_mode_rejects_explicit_remote_endpoint(monkeypatch, variable):
    from jev_ultrafast import demo

    monkeypatch.setattr(demo, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.delenv("BU_CDP_WS", raising=False)
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    monkeypatch.setenv(variable, "ws://127.0.0.1:9222/devtools/browser/stale")
    with pytest.raises(RuntimeError, match="local discovery"):
        demo.require_personal_chrome()


@pytest.mark.parametrize("url", ["https://shopee.co.th/", "https://www.lazada.co.th/a?b=1", "http://localhost:8766/"])
def test_custom_start_url_accepts_web_addresses(url):
    from jev_ultrafast.demo import custom_start_url

    assert custom_start_url(url) == url


@pytest.mark.parametrize("url", ["", "shopee.co.th", "file:///etc/passwd", "https://user:pass@shop.test/",
                                  "https://shop.test:bad/", "https://shop.test/a b"])
def test_custom_start_url_rejects_invalid_addresses(url):
    from jev_ultrafast.demo import custom_start_url

    with pytest.raises(ValueError, match="starting URL"):
        custom_start_url(url)


def test_custom_reset_uses_given_url_and_goal(monkeypatch):
    from jev_ultrafast import demo

    monkeypatch.delenv("JEV_BROWSER_MODE", raising=False)
    monkeypatch.setattr(demo, "AGENT", None)
    agent = Mock()
    agent.state = {}
    agent.snapshot.return_value = {"status": "ready"}
    factory = Mock(return_value=agent)
    monkeypatch.setattr(demo, "Agent", factory)
    result = demo.command("reset", {"scenario": "custom", "url": "https://www.lazada.co.th/", "goal": "Find a mug"})
    assert factory.call_args.args == ("https://www.lazada.co.th/", "Find a mug")
    assert agent.state["scenario"] == "custom"
    assert result["status"] == "ready"


@pytest.mark.parametrize("dedicated", [False, True])
def test_only_dedicated_demo_tab_is_brought_to_front(monkeypatch, dedicated):
    import jev_ultrafast.browser as browser

    monkeypatch.delenv("JEV_BROWSER_MODE", raising=False)
    if dedicated:
        monkeypatch.setenv("JEV_DEDICATED_CHROME", "1")
    else:
        monkeypatch.delenv("JEV_DEDICATED_CHROME", raising=False)
    calls = []

    def fake_cdp(method, **_kwargs):
        calls.append(method)
        if method == "Target.createTarget":
            return {"targetId": "target"}
        if method == "Target.attachToTarget":
            return {"sessionId": "session"}
        return {}

    monkeypatch.setattr(browser, "cdp", fake_cdp)
    monkeypatch.setattr(browser, "ensure_daemon", Mock())
    monkeypatch.setattr(browser.Browser, "evaluate", lambda _self, _expression: "complete")
    browser.Browser("https://example.test")
    assert ("Page.bringToFront" in calls) is dedicated


@pytest.mark.parametrize("user_agent", ["HeadlessChrome/153.0", ""])
def test_personal_mode_rejects_headless_or_unknown_chrome(monkeypatch, user_agent):
    import jev_ultrafast.browser as browser

    monkeypatch.setenv("JEV_BROWSER_MODE", "personal")
    monkeypatch.setattr(browser, "ensure_daemon", Mock())
    cdp = Mock(return_value={"userAgent": user_agent})
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="visible Chrome"):
        browser.Browser("https://example.test")
    assert cdp.call_args.args == ("Browser.getVersion",)


def test_personal_mode_brings_owned_tab_to_front(monkeypatch):
    import jev_ultrafast.browser as browser

    monkeypatch.setenv("JEV_BROWSER_MODE", "personal")
    monkeypatch.delenv("JEV_DEDICATED_CHROME", raising=False)
    calls = []

    def fake_cdp(method, **_kwargs):
        calls.append(method)
        return {"Browser.getVersion": {"userAgent": "Chrome/153.0"},
                "Target.createTarget": {"targetId": "target"},
                "Target.attachToTarget": {"sessionId": "session"}}.get(method, {})

    monkeypatch.setattr(browser, "cdp", fake_cdp)
    monkeypatch.setattr(browser, "ensure_daemon", Mock())
    monkeypatch.setattr(browser.Browser, "evaluate", lambda _self, _expression: "complete")
    browser.Browser("https://example.test")
    assert "Page.bringToFront" in calls


def test_executor_rejects_a_stale_page_before_browser_input(monkeypatch):
    import jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.fresh = Mock(return_value=False)
    operation = Mock()
    monkeypatch.setattr(browser, "browser_operation", operation)
    with pytest.raises(StalePage):
        b.act(page()["actions"][0], page(), "book")
    operation.assert_not_called()


@pytest.mark.parametrize("response", [{"exceptionDetails": {}}, {"result": {}}])
def test_interrupted_dropdown_mutation_cannot_be_retried_as_stale(monkeypatch, response):
    import jev_ultrafast.browser as browser

    # A navigation can destroy the evaluation result after the change event already fired.
    if "exceptionDetails" in response:
        response["exceptionDetails"] = {"text": "Execution context destroyed"}
    cdp = Mock(return_value=response)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="Dropdown execution"):
        browser_operation({"operation": "act", "session": "test", "action": {
            "id": "e1", "kind": "select", "node": 1, "value": "Design",
        }})
    assert cdp.call_count == 1


def test_fingerprint_tracks_values_and_identity_not_screenshots():
    p = page()
    other = deepcopy(p)
    other["screenshot"] = "changed"
    assert fingerprint(p) == fingerprint(other)
    other["actions"][0]["node"] = 99
    assert fingerprint(p) != fingerprint(other)


@pytest.mark.parametrize("changed", ["Departure", "Where from?", "Where to?", "year"])
def test_flight_verification_rejects_wrong_trip(changed):
    from examples.flights import verify

    actual = {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": "Track prices from Zürich to London departing 2026-09-20",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from?", "Zürich"),
                ("Where to?", "London"),
                ("Departure", "Sun, Sep 20"),
                ("Nonstop flight on Sunday, September 20. Select flight", ""),
            ]
        ],
    }
    assert verify(actual, date(2026, 9, 20))["passed"]
    if changed == "year":
        actual["text"] = actual["text"].replace("2026", "2027")
    else:
        next(a for a in actual["actions"] if a["label"] == changed)["value"] = "wrong"
    assert not verify(actual, date(2026, 9, 20))["passed"]


@pytest.mark.parametrize(
    "content", ["Thinking: Zurich", '{"text":null}', '{"text":"Zurich","extra":true}', '{"text":123}']
)
def test_text_helper_rejects_invalid_values(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "Find a flight"})


def test_navigation_during_prediction_reobserves_without_action(runner):
    runner.state["browser"].fresh.side_effect = StalePage("Document navigating")
    runner.command("tick")
    assert runner.state["status"] == "ready"
    assert runner.state["decision"] is None
    runner.state["browser"].act.assert_not_called()
