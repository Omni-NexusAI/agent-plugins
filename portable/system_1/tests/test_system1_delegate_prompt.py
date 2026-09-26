import json
from pathlib import Path
import unittest


PROMPT = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" /
          "prompts" / "agent.system.tool.system1_delegate.md")
EXAMPLE = '{"tool_name":"system1_delegate","tool_args":{"action_ids":["listed_action_id"]}}'


class System1DelegatePromptTests(unittest.TestCase):
    def test_main_visible_prompt_documents_the_exact_bounded_host_schema(self):
        text = PROMPT.read_text(encoding="utf-8")

        self.assertIn(EXAMPLE, text)
        self.assertEqual(json.loads(EXAMPLE), {
            "tool_name": "system1_delegate",
            "tool_args": {"action_ids": ["listed_action_id"]},
        })
        self.assertIn("one to eight", text.casefold())
        self.assertIn("still-eligible", text)
        self.assertIn("Do not delegate a completed call", text)

    def test_optional_goal_is_bounded_guidance_without_replay_authority(self):
        text = PROMPT.read_text(encoding="utf-8")
        self.assertIn("tool_args.goal", text)
        self.assertIn("1000 characters", text)
        self.assertIn("guidance only, not evidence or authorization", text)
        self.assertIn("Changing the goal does not permit replay", text)


if __name__ == "__main__":
    unittest.main()
