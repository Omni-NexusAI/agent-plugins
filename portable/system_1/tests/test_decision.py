import asyncio
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "core" / "decision.py"
spec = importlib.util.spec_from_file_location("system_one_decision", SOURCE)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class DecisionTests(unittest.TestCase):
    def test_jev_request_and_exact_action(self):
        captured = {}
        def fake_post(url, payload, token, timeout):
            captured.update(url=url, payload=payload, token=token)
            return {"answers": {"route": {"choice": "open", "probabilities": {"open": 0.93}}}}
        client = module.DecisionClient(backend="jev", model="jev-latest", token="test")
        with patch.object(module, "_post", fake_post):
            decision = asyncio.run(client.choose("Open the dashboard", {"main": "Reason", "open": "Open dashboard"}))
        self.assertEqual(captured["payload"]["questions"]["route"]["type"], "choice")
        self.assertEqual(captured["token"], "test")
        action = module.selected_action(decision, {"open": {"tool_name": "known_tool", "tool_args": {"target": "dashboard"}}}, threshold=0.9)
        self.assertEqual(action, {"tool_name": "known_tool", "tool_args": {"target": "dashboard"}})

    def test_llama_endpoint_and_low_probability_escalation(self):
        captured = {}
        def fake_post(url, payload, token, timeout):
            captured.update(url=url, payload=payload)
            return {"results": [{"decision": {"route": "open"}, "fields": {"route": {"probability": 0.2}}}]}
        client = module.DecisionClient(backend="llama_decision", model="local", endpoint="http://localhost:8096")
        with patch.object(module, "_post", fake_post):
            decision = asyncio.run(client.choose("State", {"main": "Reason", "open": "Open"}))
        self.assertEqual(captured["url"], "http://localhost:8096/v1/decision")
        self.assertEqual(captured["payload"]["schema"]["route"]["choices"], ["main", "open"])
        self.assertIsNone(module.selected_action(decision, {"open": {"tool_name": "known_tool"}}, threshold=0.9))

    def test_openrouter_uses_decisions_api_and_latest_alias(self):
        captured = {}
        def fake_post(url, payload, token, timeout):
            captured.update(url=url, payload=payload, token=token)
            return {"answers": {"route": {"choice": "main", "probabilities": {"main": 0.98}}}}
        client = module.DecisionClient(backend="openrouter", model="typesafe/jev-latest", token="test")
        with patch.object(module, "_post", fake_post):
            decision = asyncio.run(client.choose("State", {"main": "Reason", "tool": "Delegate"}))
        self.assertEqual(captured["url"], "https://openrouter.ai/api/alpha/decisions")
        self.assertEqual(captured["payload"]["model"], "~typesafe/jev-latest")
        self.assertEqual(decision.confidence, 0.98)

    def test_rejects_backend_choice_outside_eligibility(self):
        client = module.DecisionClient(backend="jev", model="jev-latest")
        with patch.object(module, "_post", return_value={"answers": {"route": {"choice": "other", "probabilities": {"other": 1.0}}}}):
            with self.assertRaises(module.DecisionError):
                asyncio.run(client.choose("State", {"main": "Reason", "open": "Open"}))


if __name__ == "__main__":
    unittest.main()
