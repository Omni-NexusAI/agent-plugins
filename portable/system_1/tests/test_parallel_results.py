import importlib.util
import json
from pathlib import Path
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "adapters" / "agent_zero" /
          "helpers" / "parallel_results.py")
SPEC = importlib.util.spec_from_file_location("system_one_parallel_results_test", SOURCE)
PARALLEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARALLEL)


class ParallelResultContractTests(unittest.TestCase):
    def setUp(self):
        self.batch = [
            {"tool_name": "github_mcp_server.get_pull_request_status",
             "tool_args": {"owner": "Omni-NexusAI", "repo": "agent-plugins", "pull_number": 11}},
            {"tool_name": "memory_load", "tool_args": {"query": "current project"}},
        ]

    def test_completed_jobs_are_ordered_and_attributed_to_the_expected_children(self):
        aggregate = json.dumps({
            "status": "success",
            "jobs": [
                {"job_id": "status-11", "tool_name": "github_mcp_server.get_pull_request_status",
                 "state": "success", "result": "{\"state\":\"open\"}"},
                {"job_id": "memory-project", "tool_name": "memory_load",
                 "state": "success", "result": "project context"},
            ],
        })

        jobs = PARALLEL.parse_parallel_jobs(
            aggregate, self.batch, ["status-11", "memory-project"])

        self.assertEqual([job["job_id"] for job in jobs], ["status-11", "memory-project"])
        self.assertEqual([job["tool_name"] for job in jobs], [
            "github_mcp_server.get_pull_request_status", "memory_load"])
        self.assertEqual(jobs[0]["result"], '{"state":"open"}')

    def test_started_jobs_carry_no_completed_result_until_an_await_aggregate_arrives(self):
        started = json.dumps({
            "status": "started",
            "jobs": [
                {"job_id": "status-11", "tool_name": "github_mcp_server.get_pull_request_status",
                 "state": "running"},
                {"job_id": "memory-project", "tool_name": "memory_load", "state": "pending"},
            ],
        })

        jobs = PARALLEL.parse_parallel_jobs(started, self.batch)

        self.assertEqual([job["state"] for job in jobs], ["running", "pending"])
        self.assertEqual([job["result"] for job in jobs], ["", ""])

    def test_await_aggregate_maps_reordered_jobs_by_recorded_id(self):
        aggregate = json.dumps({
            "status": "success",
            "jobs": [
                {"job_id": "memory-project", "tool_name": "memory_load",
                 "state": "success", "result": "wrong order"},
                {"job_id": "status-11", "tool_name": "github_mcp_server.get_pull_request_status",
                 "state": "success", "result": "wrong order"},
            ],
        })

        jobs = PARALLEL.parse_parallel_jobs(
            aggregate, self.batch, ["status-11", "memory-project"])
        self.assertEqual([job["batch_index"] for job in jobs], [1, 0])

    def test_await_subset_retains_its_original_child_index_and_rejects_duplicate_jobs(self):
        subset = json.dumps({
            "status": "partial",
            "jobs": [{"job_id": "memory-project", "tool_name": "memory_load",
                      "state": "success", "result": "project context"}],
        })
        duplicate = json.dumps({
            "status": "partial",
            "jobs": [
                {"job_id": "memory-project", "tool_name": "memory_load",
                 "state": "success", "result": "project context"},
                {"job_id": "memory-project", "tool_name": "memory_load",
                 "state": "success", "result": "replayed"},
            ],
        })

        jobs = PARALLEL.parse_parallel_jobs(
            subset, self.batch, ["status-11", "memory-project"])
        self.assertEqual([(job["batch_index"], job["job_id"]) for job in jobs],
                         [(1, "memory-project")])
        self.assertIsNone(PARALLEL.parse_parallel_jobs(
            duplicate, self.batch, ["status-11", "memory-project"]))

    def test_await_accepts_a_tracked_child_among_more_than_eight_mixed_jobs(self):
        """Later awaits may contain unrelated Main jobs beyond the initial batch cap."""
        aggregate = json.dumps({
            "status": "partial",
            "jobs": [
                {"job_id": f"main-{index}", "tool_name": "code_execution_tool",
                 "state": "success", "result": "unrelated Main result"}
                for index in range(8)
            ] + [
                {"job_id": "memory-project", "tool_name": "memory_load",
                 "state": "success", "result": "project context"},
            ],
        })

        jobs = PARALLEL.parse_parallel_jobs(
            aggregate, self.batch, ["status-11", "memory-project"])

        self.assertEqual(jobs, [{
            "job_id": "memory-project",
            "tool_name": "memory_load",
            "state": "success",
            "result": "project context",
            "error": "",
            "batch_index": 1,
        }])

    def test_failed_or_interrupted_children_are_retained_as_status_only(self):
        aggregate = json.dumps({
            "status": "partial",
            "jobs": [
                {"job_id": "status-11", "tool_name": "github_mcp_server.get_pull_request_status",
                 "state": "timeout", "error": "worker timed out"},
                {"job_id": "memory-project", "tool_name": "memory_load",
                 "state": "cancelled", "error": "interrupted"},
            ],
        })

        jobs = PARALLEL.parse_parallel_jobs(
            aggregate, self.batch, ["status-11", "memory-project"])

        self.assertEqual([job["state"] for job in jobs], ["timeout", "cancelled"])
        self.assertEqual([job["result"] for job in jobs], ["", ""])
        self.assertEqual([job["error"] for job in jobs], ["worker timed out", "interrupted"])


if __name__ == "__main__":
    unittest.main()
