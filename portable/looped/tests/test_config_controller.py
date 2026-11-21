import copy
import unittest

import support  # noqa: F401
from core import DEFAULTS, TurnState, build_candidate, checkpoint, is_active, merge_config
from core.controller import is_risky
from core.sampling import variant_params
from support import final, step


class ConfigTests(unittest.TestCase):
    def test_empty_and_corrupt_input_yield_defaults(self):
        for saved in (None, {}, "text", ["list"]):
            self.assertEqual(merge_config(saved), merge_config())
        self.assertEqual(merge_config()["mode"], "manual")

    def test_partial_settings_keep_other_defaults_and_unknown_keys(self):
        cfg = merge_config({"mode": "auto", "strategies": {"fuse": {"min_chars": 10}},
                            "future_key": {"kept": True}})
        self.assertEqual(cfg["mode"], "auto")
        self.assertEqual(cfg["strategies"]["fuse"], {"enabled": True, "min_chars": 10})
        self.assertTrue(cfg["strategies"]["agree"]["enabled"])
        self.assertEqual(cfg["future_key"], {"kept": True})

    def test_bad_values_are_clamped_or_reset(self):
        cfg = merge_config({"mode": "sometimes", "budget": {"max_extra_calls_per_turn": 9999,
                                                            "max_extra_calls_per_step": True},
                            "strategies": "broken", "sampling": {"temperature": "hot"},
                            "auto": {"checkpoints": ["first_step", "made_up"], "risky_tools": 5}})
        self.assertEqual(cfg["mode"], "manual")
        self.assertEqual(cfg["budget"]["max_extra_calls_per_turn"], 64)
        self.assertEqual(cfg["budget"]["max_extra_calls_per_step"], 1)
        self.assertEqual(cfg["strategies"], merge_config()["strategies"])
        self.assertIsNone(cfg["sampling"]["temperature"])
        self.assertEqual(cfg["auto"]["checkpoints"], ["first_step"])
        self.assertEqual(cfg["auto"]["risky_tools"], DEFAULTS["auto"]["risky_tools"])

    def test_merging_never_mutates_the_defaults(self):
        thinking = {"strategies": {"escalate": {"enabled": True,
                                                "reasoning_params": {"reasoning_effort": "high"}}}}
        self.assertEqual(merge_config(thinking)["strategies"]["escalate"]["reasoning_params"],
                         {"reasoning_effort": "high"})      # replaced whole, not merged
        self.assertEqual(merge_config({"strategies": {"escalate": {"reasoning_params": 5}}})
                         ["strategies"]["escalate"],
                         DEFAULTS["strategies"]["escalate"])
        snapshot = copy.deepcopy(DEFAULTS)
        cfg = merge_config({"auto": {"risky_tools": ["x"]}})
        cfg["strategies"]["agree"]["enabled"] = False
        cfg["auto"]["checkpoints"].append("x")
        self.assertEqual(DEFAULTS, snapshot)

    def test_extra_samples_get_a_distinct_seed_and_temperature(self):
        cfg = merge_config()
        self.assertEqual(variant_params(cfg, 0), {})
        self.assertEqual(variant_params(cfg, 1), {"seed": 1001, "temperature": 0.7})
        cfg = merge_config({"sampling": {"temperature": None}})
        self.assertEqual(variant_params(cfg, 2), {"seed": 1002})


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.action = build_candidate(step("search_engine", query="x"))
        self.risky = build_candidate(step("code_execution_tool", code="rm x"))
        self.answer = build_candidate(final("done"))
        self.invalid = build_candidate("garbage")

    def test_modes(self):
        armed = TurnState(armed=True)
        for mode, idle, when_armed in (("off", False, False), ("manual", False, True),
                                       ("auto", True, True), ("always", True, True)):
            cfg = merge_config({"mode": mode})
            self.assertEqual(is_active(cfg, TurnState()), idle, mode)
            self.assertEqual(is_active(cfg, armed), when_armed, mode)

    def test_chat_mode_overrides_saved_mode(self):
        cfg = merge_config({"mode": "off"})
        self.assertTrue(is_active(cfg, TurnState(), chat_mode="always"))
        self.assertFalse(is_active(merge_config({"mode": "always"}), TurnState(), chat_mode="off"))
        self.assertFalse(is_active(cfg, TurnState(), chat_mode="bogus"))

    def test_auto_checkpoints(self):
        cfg = merge_config({"mode": "auto"})
        self.assertEqual(checkpoint(cfg, TurnState(), self.action, 0), "first_step")
        self.assertIsNone(checkpoint(cfg, TurnState(), self.action, 3))
        self.assertEqual(checkpoint(cfg, TurnState(), self.risky, 3), "risky_tool")
        self.assertEqual(checkpoint(cfg, TurnState(), self.answer, 3), "final_response")
        self.assertEqual(checkpoint(cfg, TurnState(), self.invalid, 3), "invalid_step")
        self.assertEqual(checkpoint(cfg, TurnState(retry_armed=True), self.action, 3), "after_error")

    def test_disabled_checkpoints_do_not_fire(self):
        cfg = merge_config({"mode": "auto", "auto": {"checkpoints": ["risky_tool"]}})
        self.assertIsNone(checkpoint(cfg, TurnState(), self.answer, 0))
        self.assertEqual(checkpoint(cfg, TurnState(), self.risky, 0), "risky_tool")

    def test_always_and_armed_fire_on_every_step(self):
        self.assertEqual(checkpoint(merge_config({"mode": "always"}), TurnState(), self.action, 5), "always")
        self.assertEqual(checkpoint(merge_config(), TurnState(armed=True), self.action, 5), "armed")
        self.assertIsNone(checkpoint(merge_config(), TurnState(), self.risky, 0))

    def test_budget_stops_checkpoints(self):
        cfg = merge_config({"mode": "always", "budget": {"max_extra_calls_per_turn": 2}})
        self.assertIsNone(checkpoint(cfg, TurnState(extra_calls=2), self.risky, 0))
        cfg = merge_config({"mode": "always", "budget": {"max_extra_calls_per_step": 0}})
        self.assertIsNone(checkpoint(cfg, TurnState(), self.risky, 0))

    def test_risky_patterns(self):
        patterns = DEFAULTS["auto"]["risky_tools"]
        self.assertTrue(is_risky("code_execution_tool", patterns))
        self.assertTrue(is_risky("text_editor:write", patterns))
        self.assertTrue(is_risky("github.create_issue", patterns))
        self.assertFalse(is_risky("search_engine", patterns))
        self.assertFalse(is_risky("response", patterns))


if __name__ == "__main__":
    unittest.main()
