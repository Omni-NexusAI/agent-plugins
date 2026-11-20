import unittest

import support  # noqa: F401  (sets the import path)
from core import build_candidate, canonical_key, parse_step
from core.verify import check


class ParseTests(unittest.TestCase):
    def test_parses_object_wrapped_in_prose_and_fences(self):
        text = 'Sure.\n```json\n{"tool_name": "a", "tool_args": {"x": "}"}}\n```\ntrailing'
        self.assertEqual(parse_step(text)["tool_args"], {"x": "}"})

    def test_repairs_trailing_comma(self):
        self.assertEqual(parse_step('{"tool_name": "a", "tool_args": {"x": 1,},}')["tool_name"], "a")

    def test_rejects_text_without_an_object(self):
        self.assertIsNone(parse_step("no json here"))
        self.assertIsNone(parse_step("{broken"))
        self.assertIsNone(parse_step(None))


class KeyTests(unittest.TestCase):
    def test_cosmetic_differences_do_not_change_the_key(self):
        first = canonical_key("Code_Tool", {"b": 1.0, "a": "x  y \r\n"})
        second = canonical_key("code_tool ", {"a": "x y", "b": 1})
        self.assertEqual(first, second)

    def test_multiline_strings_keep_line_structure(self):
        first = canonical_key("t", {"code": "if a:\n    b()  \n"})
        second = canonical_key("t", {"code": "if a:\n    b()"})
        different = canonical_key("t", {"code": "if a:\nb()"})
        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_real_argument_differences_change_the_key(self):
        self.assertNotEqual(canonical_key("t", {"path": "a.txt"}),
                            canonical_key("t", {"path": "b.txt"}))
        self.assertNotEqual(canonical_key("t", {"n": 1}), canonical_key("u", {"n": 1}))

    def test_final_answers_compare_loosely(self):
        self.assertEqual(canonical_key("response", {"text": "**42**."}, final=True),
                         canonical_key("response", {"text": " 42 "}, final=True))


class CandidateTests(unittest.TestCase):
    def test_classifies_action_final_and_invalid(self):
        action = build_candidate('{"tool_name": "search", "tool_args": {"q": "x"}}')
        answer = build_candidate('{"tool_name": "response", "tool_args": {"text": "hi"}}')
        legacy = build_candidate('{"tool": "search", "args": {"q": "x"}}')
        self.assertEqual((action.kind, answer.kind, legacy.kind), ("action", "final", "action"))
        self.assertEqual(action.key, legacy.key)
        for raw, problem in (("nothing", "unparsed"),
                             ('{"tool_args": {}}', "no_tool_name"),
                             ('{"tool_name": "a", "tool_args": "x"}', "args_not_object")):
            candidate = build_candidate(raw)
            self.assertFalse(candidate.valid)
            self.assertEqual(candidate.problems, [problem])

    def test_host_parser_is_used_and_its_errors_are_contained(self):
        candidate = build_candidate("x", parser=lambda _: {"tool_name": "a", "tool_args": {"k": 1}})
        self.assertEqual(candidate.tool_name, "a")

        def broken(_):
            raise RuntimeError("parser failed")
        self.assertEqual(build_candidate("x", parser=broken).problems, ["unparsed"])

    def test_checks_tool_existence_and_repeats(self):
        raw = '{"tool_name": "search:web", "tool_args": {"q": "x"}}'
        self.assertTrue(check(build_candidate(raw), tool_names=["search"]).valid)
        self.assertTrue(check(build_candidate(raw), tool_names=None).valid)
        unknown = check(build_candidate(raw), tool_names=["other"])
        self.assertEqual((unknown.kind, unknown.problems), ("invalid", ["unknown_tool"]))
        repeat = check(build_candidate(raw), last_response=raw + "\n")
        self.assertEqual(repeat.problems, ["repeat"])


if __name__ == "__main__":
    unittest.main()
