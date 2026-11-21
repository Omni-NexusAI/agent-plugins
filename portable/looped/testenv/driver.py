"""Drive the scenarios against the test Agent Zero. Runs inside the test network.

Standard library only. For each scenario it loads the stub model's script,
saves the plugin settings, sends one chat message, waits for the turn to end,
and checks what the agent logged and what the stub model was asked.
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

A0 = os.environ.get("LOOPED_TEST_A0", "http://looped-test-a0:80").rstrip("/")
STUB = os.environ.get("LOOPED_TEST_STUB", "http://looped-test-llm:8000").rstrip("/")
SCENARIOS = Path(os.environ.get("LOOPED_TEST_SCENARIOS", "/testenv/scenarios.py"))
RESULTS = Path(os.environ.get("LOOPED_TEST_RESULTS", "/results"))
BOOT_TIMEOUT = int(os.environ.get("LOOPED_TEST_BOOT_TIMEOUT", "420"))
ORIGIN = "http://localhost"


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.token = ""
        self.prefix = ""

    def request(self, url, body=None, headers=None, timeout=60):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
        request.add_header("Origin", ORIGIN)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        with self.opener.open(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
        try:
            return json.loads(text)
        except ValueError:
            return {"_text": text}

    def login(self):
        last = None
        for prefix in ("/api", ""):
            try:
                reply = self.request(f"{A0}{prefix}/csrf_token")
            except Exception as error:   # try the other URL layout
                last = error
                continue
            if isinstance(reply, dict) and reply.get("token"):
                self.token, self.prefix = reply["token"], prefix
                cookie = http.cookiejar.Cookie(
                    0, "csrf_token_" + str(reply.get("runtime_id", "")), self.token, None, False,
                    A0.split("//")[1].split(":")[0], False, False, "/", True, False, None, False,
                    None, None, {})
                self.jar.set_cookie(cookie)
                return
            last = reply
        raise RuntimeError(f"could not get a CSRF token: {last}")

    def api(self, name, body, timeout=60):
        return self.request(f"{A0}{self.prefix}/{name}", body,
                            {"X-CSRF-Token": self.token}, timeout)


def wait_for(url, seconds, what):
    deadline = time.time() + seconds
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return
        except urllib.error.HTTPError as error:
            if error.code < 500:
                return
            last = str(error)
        except Exception as error:
            last = str(error)
        time.sleep(3)
    raise RuntimeError(f"{what} did not come up within {seconds}s ({last})")


def stub(path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(STUB + path, data=data,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def flatten(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def run_scenario(client: Client, scenario: dict) -> dict:
    stub("/__admin/scenario", {"main": scenario.get("main", []),
                               "plan": scenario.get("plan", []),
                               "default": scenario.get("default", "ok")})
    saved = client.api("plugins", {"action": "save_config", "plugin_name": "looped",
                                   "settings": scenario.get("settings", {})})
    if not (isinstance(saved, dict) and saved.get("ok")):
        return {"passed": False, "failures": [f"could not save settings: {saved}"]}

    # A fresh chat per scenario: per-chat mode, the one-shot arm and the chat
    # log must not carry over from the scenario before.
    context = "looped-" + uuid.uuid4().hex[:16]
    created = client.api("chat_create", {"new_context": context})
    if not isinstance(created, dict) or created.get("_text"):
        return {"passed": False, "failures": [f"could not create a chat: {created}"]}
    logs: dict[int, dict] = {}
    for message in scenario.get("messages", []):
        reply = client.api("message_async", {"text": message["text"], "context": context})
        context = reply.get("context", context)
        wait_text = message.get("wait_for")
        deadline = time.time() + int(message.get("timeout", 150))
        seen = False
        while time.time() < deadline:
            snapshot = client.api("poll", {"context": context, "log_from": 0})
            for item in snapshot.get("logs") or []:
                logs[item.get("no", len(logs))] = item
            text = "\n".join(flatten(item.get("content")) for item in logs.values())
            if wait_text and wait_text in text:
                seen = True
                break
            if not wait_text and time.time() > deadline - int(message.get("timeout", 150)) + int(message.get("settle", 6)):
                seen = True
                break
            time.sleep(1.5)
        if not seen:
            break
        time.sleep(float(message.get("after", 2)))

    snapshot = client.api("poll", {"context": context, "log_from": 0})
    for item in snapshot.get("logs") or []:
        logs[item.get("no", len(logs))] = item
    items = [logs[key] for key in sorted(logs)]
    calls = stub("/__admin/log")
    mode = client.api("plugins/looped/mode", {"context_id": context, "action": "get"})
    outcome = check(scenario, items, calls, mode)
    try:
        client.api("chat_remove", {"context": context})
    except Exception:
        pass
    return outcome


def check(scenario: dict, items: list, calls: dict, mode: dict) -> dict:
    expect = scenario.get("expect", {})
    failures = []
    headings = [str(item.get("heading") or "") for item in items]
    everything = "\n".join(flatten(item.get("heading")) + "\n" + flatten(item.get("content")) +
                           "\n" + flatten(item.get("kvps")) for item in items)
    user_text = "\n".join(flatten(item.get("content")) for item in items if item.get("type") == "user")
    main_calls = [call for call in calls.get("log", []) if call["kind"] == "main"]
    plan_calls = [call for call in calls.get("log", []) if call["kind"] == "plan"]

    def need(condition, message):
        if not condition:
            failures.append(message)

    if "main_calls" in expect:
        need(len(main_calls) == expect["main_calls"],
             f"main model calls: expected {expect['main_calls']}, saw {len(main_calls)}")
    if "plan_calls" in expect:
        need(len(plan_calls) == expect["plan_calls"],
             f"planning calls: expected {expect['plan_calls']}, saw {len(plan_calls)}")
    for text in expect.get("log_contains", []):
        need(text in everything, f"chat log lacks {text!r}")
    for text in expect.get("log_lacks", []):
        need(text not in everything, f"chat log unexpectedly contains {text!r}")
    for text in expect.get("heading_contains", []):
        need(any(text in heading for heading in headings), f"no timeline step titled {text!r}")
    for text in expect.get("heading_lacks", []):
        need(not any(text in heading for heading in headings),
             f"unexpected timeline step titled {text!r}")
    for text in expect.get("user_message_lacks", []):
        need(text not in user_text, f"user message still shows {text!r}")
    if "extra_calls" in expect:
        # The host's own call streams and has no seed; an extra pass is not
        # streamed and carries its own seed.
        extras = [call for call in main_calls if call.get("seed") is not None]
        need(len(extras) == expect["extra_calls"],
             f"extra passes: expected {expect['extra_calls']}, saw {len(extras)}")
        need(all(not call.get("stream") for call in extras), "an extra pass was streamed")
        need(all(call.get("stream") for call in main_calls if call.get("seed") is None),
             "a host call was not streamed")
    for flag in ("reread", "fuse", "deepen", "retry_note", "plan_note"):
        if flag in expect:
            seen = any(call.get(flag) for call in main_calls)
            need(seen == expect[flag], f"{flag}: expected {expect[flag]}, saw {seen}")
    if "slash_token_in_prompt" in expect:
        seen = any(call.get("slash_token") for call in main_calls)
        need(seen == expect["slash_token_in_prompt"],
             f"'/looped' reached the model prompt: {seen}")
    if "mode" in expect:
        need(mode.get("mode") == expect["mode"],
             f"chat mode: expected {expect['mode']!r}, saw {mode.get('mode')!r}")
    if "armed" in expect:
        need(bool(mode.get("armed")) == expect["armed"],
             f"armed: expected {expect['armed']}, saw {mode.get('armed')}")
    need(calls.get("main_left", 0) == expect.get("main_left", 0),
         f"scripted replies left unused: {calls.get('main_left')}")
    return {"passed": not failures, "failures": failures,
            "main_calls": len(main_calls), "headings": [h for h in headings if h.startswith("Looped")]}


def api_and_assets(client: Client) -> dict:
    """Per-chat mode API, metrics API, and that the UI files are served."""
    failures = []

    def need(condition, message):
        if not condition:
            failures.append(message)

    context = "looped-" + uuid.uuid4().hex[:16]
    client.api("chat_create", {"new_context": context})
    mode = lambda **body: client.api("plugins/looped/mode", {"context_id": context, **body})  # noqa: E731
    need(mode(action="get").get("mode") is None, "a new chat should have no per-chat mode")
    need(mode(action="set", mode="always").get("mode") == "always", "set mode did not stick")
    need(mode(action="arm").get("armed") is True, "arm did not stick")
    need(mode(action="arm", armed=False).get("armed") is False, "disarm did not stick")
    reply = mode(action="command", text="/looped auto then go")
    need(reply.get("mode") == "auto" and reply.get("rest") == "then go",
         f"command action returned {reply}")
    need(mode(action="set", mode="default").get("mode") is None, "reset to default failed")
    metrics = client.api("plugins/looped/metrics", {"context_id": context})
    need(metrics.get("ok") is True and "steps" in (metrics.get("metrics") or {}),
         f"metrics API returned {metrics}")
    try:
        client.api("plugins/looped/mode", {"context_id": context, "action": "set", "mode": "bogus"})
        failures.append("an unknown mode was accepted")
    except urllib.error.HTTPError as error:
        need(error.code == 400, f"unknown mode gave HTTP {error.code}")
    for path, marker in (
            ("webui/config.html", "Looped Mode"),
            ("extensions/webui/chat-input-progress-start/looped-toggle.html", "looped-toggle"),
            ("extensions/webui/send_message_before/_05_looped.js", "loopedCommand")):
        served = ""
        for base in ("/usr/plugins/looped/", "/plugins/looped/"):
            try:
                served = client.request(f"{A0}{base}{path}").get("_text", "")
            except Exception:
                continue
            if marker in served:
                break
        need(marker in served, f"UI file not served: {path}")
    try:
        client.api("chat_remove", {"context": context})
    except Exception:
        pass
    return {"passed": not failures, "failures": failures}


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    print(f"waiting for the stub model at {STUB} ...", flush=True)
    wait_for(STUB + "/health", 60, "stub model")
    print(f"waiting for Agent Zero at {A0} (first start copies its files) ...", flush=True)
    wait_for(A0 + "/", BOOT_TIMEOUT, "Agent Zero")
    client = Client()
    deadline = time.time() + 120
    while True:
        try:
            client.login()
            break
        except Exception:
            if time.time() > deadline:
                raise
            time.sleep(4)

    sys.path.insert(0, str(SCENARIOS.parent))
    from scenarios import SCENARIOS as scripted

    wanted = [name for name in os.environ.get("LOOPED_TEST_ONLY", "").split(",") if name]
    results = {}
    for name, scenario in sorted(scripted.items()):
        if wanted and name not in wanted:
            continue
        print(f"--- {name}: {scenario.get('description', '')}", flush=True)
        try:
            outcome = run_scenario(client, scenario)
        except Exception as error:
            outcome = {"passed": False, "failures": [f"driver error: {error!r}"]}
        results[name] = outcome
        print(("PASS" if outcome["passed"] else "FAIL") + f"  {name}", flush=True)
        for failure in outcome["failures"]:
            print(f"      {failure}", flush=True)

    if not wanted or "13_api_and_assets" in wanted:
        name = "13_api_and_assets"
        print(f"--- {name}: Per-chat mode API, metrics API, UI files are served.", flush=True)
        try:
            outcome = api_and_assets(client)
        except Exception as error:
            outcome = {"passed": False, "failures": [f"driver error: {error!r}"]}
        results[name] = outcome
        print(("PASS" if outcome["passed"] else "FAIL") + f"  {name}", flush=True)
        for failure in outcome["failures"]:
            print(f"      {failure}", flush=True)

    passed = sum(1 for outcome in results.values() if outcome["passed"])
    summary ={"passed": passed, "failed": len(results) - passed, "scenarios": results}
    (RESULTS / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(results)} scenarios passed", flush=True)
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
