import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" / "hooks.py"
SPEC = importlib.util.spec_from_file_location("system_one_hooks_test", SOURCE)
HOOKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOKS)


class ActionConfigTests(unittest.TestCase):
    def test_independent_action_requires_boolean_opt_in(self):
        action = {"tool_name": "known_tool", "tool_args": {"query": "fixed"},
                  "independent_while_main": True}
        settings = {"policy": {"actions": {"known": action}}}
        self.assertIs(HOOKS.save_plugin_config(settings=settings), settings)
        action["independent_while_main"] = "true"
        with self.assertRaises(ValueError):
            HOOKS.save_plugin_config(settings=settings)

    def test_independent_action_defaults_off(self):
        settings = {"policy": {"actions": {
            "known": {"tool_name": "known_tool", "tool_args": {"query": "fixed"}}}}}
        self.assertIs(HOOKS.save_plugin_config(settings=settings), settings)

    def test_main_control_ids_cannot_be_actions(self):
        for key in ("main", "finish", "wait_main"):
            with self.subTest(key=key):
                settings = {"policy": {"actions": {
                    key: {"tool_name": "known_tool", "tool_args": {"query": "fixed"}}}}}
                with self.assertRaises(ValueError):
                    HOOKS.save_plugin_config(settings=settings)

    def test_utility_routes_are_validated_and_ui_draft_removed(self):
        route = {"system": "Classify", "message": "Item A",
                 "responses": {"yes": "YES", "no": "NO"}}
        settings = {"utility": {"fixed_routes": [route], "_fixed_routes_json": "draft"}}
        self.assertIs(HOOKS.save_plugin_config(settings=settings), settings)
        self.assertNotIn("_fixed_routes_json", settings["utility"])
        settings["utility"]["fixed_routes"] = [route, route]
        with self.assertRaises(ValueError):
            HOOKS.save_plugin_config(settings=settings)
        settings["utility"]["fixed_routes"] = [{**route, "responses": {}}]
        with self.assertRaises(ValueError):
            HOOKS.save_plugin_config(settings=settings)


if __name__ == "__main__":
    unittest.main()
