"""Keep Main in the loop until System 1's native parallel jobs are collected."""

from helpers.extension import Extension
from usr.plugins.system_1.helpers.runtime import pending_parallel_job_ids


class SystemOneCompletionGuard(Extension):
    def execute(self, response=None, tool_name="", loop_data=None, **kwargs):
        if not self.agent or tool_name != "response" or response is None:
            return
        job_ids = pending_parallel_job_ids(self.agent)
        if not job_ids:
            return
        # The host has executed the response tool but has not yet committed it
        # as a final answer. A false break_loop makes its normal loop continue.
        response.break_loop = False
        response.message = "System 1 parallel jobs are still awaiting results."
        # LiveResponse may already have streamed the proposed answer into the
        # chat bubble before the response tool executes. Replace that bubble
        # as well as the tool response, so an unverified answer is not shown as
        # final while Agent Zero continues the loop.
        try:
            current_loop = loop_data or getattr(self.agent, "loop_data", None)
            log_item = current_loop.params_temporary.get("log_item_response")
            if log_item is not None:
                log_item.update(content=response.message)
        except (AttributeError, TypeError):
            pass
        try:
            self.agent.hist_add_warning(
                "A final answer was deferred because System 1 parallel jobs are "
                "unfinished. Await these native parallel job IDs, inspect every "
                "recorded result, then write the final answer: " + ", ".join(job_ids)
            )
        except Exception:
            # The final-answer guard must not depend on warning UI availability.
            pass
