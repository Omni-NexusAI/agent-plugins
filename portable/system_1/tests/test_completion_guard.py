import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


SOURCE = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" /
          "extensions" / "python" / "tool_execute_after" /
          "_20_system_1_completion.py")


class CompletionGuardTests(unittest.TestCase):
    def _load(self, job_ids):
        extension = types.ModuleType("helpers.extension")
        extension.Extension = type("Extension", (), {})
        runtime = types.ModuleType("usr.plugins.system_1.helpers.runtime")
        runtime.pending_parallel_job_ids = lambda agent: list(job_ids)
        modules = patch.dict(sys.modules, {extension.__name__: extension,
                                           runtime.__name__: runtime})
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location("system_one_completion_guard_test", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.SystemOneCompletionGuard()

    def test_response_is_deferred_until_every_parallel_job_is_collected(self):
        guard = self._load(["first-job", "second-job"])
        warnings = []
        guard.agent = types.SimpleNamespace(
            hist_add_warning=warnings.append,
            loop_data=types.SimpleNamespace(params_temporary={}),
        )
        response = types.SimpleNamespace(break_loop=True, message="premature answer")
        item = types.SimpleNamespace(updates=[])
        item.update = lambda **kwargs: item.updates.append(kwargs)
        guard.agent.loop_data.params_temporary["log_item_response"] = item

        guard.execute(response=response, tool_name="response")

        self.assertFalse(response.break_loop)
        self.assertEqual(response.message, "System 1 parallel jobs are still awaiting results.")
        self.assertEqual(item.updates, [{"content": response.message}])
        self.assertEqual(len(warnings), 1)
        self.assertIn("first-job, second-job", warnings[0])

    def test_response_is_allowed_after_full_parallel_collection(self):
        guard = self._load([])
        warnings = []
        guard.agent = types.SimpleNamespace(hist_add_warning=warnings.append)
        response = types.SimpleNamespace(break_loop=True, message="completed answer")

        guard.execute(response=response, tool_name="response")

        self.assertTrue(response.break_loop)
        self.assertEqual(response.message, "completed answer")
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
