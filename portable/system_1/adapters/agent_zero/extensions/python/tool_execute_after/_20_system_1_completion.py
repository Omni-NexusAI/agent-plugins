"""Keep Main in the loop until System 1's native parallel jobs are collected."""

from helpers.extension import Extension
from usr.plugins.system_1.helpers.runtime import (
    final_response_integrity, has_unresolved_parallel_start, pending_parallel_job_ids,
)


class SystemOneCompletionGuard(Extension):
    def execute(self, response=None, tool_name="", loop_data=None, **kwargs):
        if not self.agent or tool_name != "response" or response is None:
            return
        job_ids = pending_parallel_job_ids(self.agent)
        unresolved_start = has_unresolved_parallel_start(self.agent)
        tool = getattr(getattr(self.agent, "loop_data", None), "current_tool", None)
        args = getattr(tool, "args", None)
        integrity = (final_response_integrity(self.agent, args)
                     if not job_ids and not unresolved_start else None)
        if not job_ids and not unresolved_start and not integrity:
            return
        # The host has executed the response tool but has not yet committed it
        # as a final answer. A false break_loop makes its normal loop continue.
        if job_ids:
            response.break_loop = False
            response.message = "System 1 parallel jobs are still awaiting results."
            warning = (
                "A final answer was deferred because System 1 parallel jobs are "
                "unfinished. Await these native parallel job IDs, inspect every "
                "recorded result, then write the final answer: " + ", ".join(job_ids)
            )
        elif unresolved_start:
            response.break_loop = False
            response.message = "System 1 parallel job identities are not yet verified."
            warning = (
                "A System 1 parallel submission has no verified job receipt. Do "
                "not repeat its calls or finish from uncollected work. Use only "
                "the exact native parallel job IDs supplied by the host's "
                "parallel jobs prompt entries; await or cancel those jobs and "
                "inspect their terminal results before finishing. Do not invent IDs."
            )
        elif integrity == "retry":
            response.break_loop = False
            response.message = "The final answer format was invalid; Main is retrying."
            warning = (
                "The previous response tool arguments were malformed and may have "
                "split the answer into unexpected fields. Use the recorded tool "
                "evidence without repeating successful calls. Reissue the complete "
                "answer as one valid JSON string in tool_args.text, escaping quotes "
                "and newlines."
            )
        else:
            response.break_loop = True
            response.message = (
                "I could not format a complete answer reliably. Please retry "
                "the request."
            )
            warning = "The final response remained malformed after two retries."
        # LiveResponse may already have streamed the proposed answer into the
        # chat bubble before the response tool executes. Replace that bubble
        # as well as the tool response, so an unverified answer is not shown as
        # final while Agent Zero continues the loop.
        try:
            current_loop = loop_data or getattr(self.agent, "loop_data", None)
            log_item = current_loop.params_temporary.get("log_item_response")
            if log_item is not None:
                log_item.update(content=response.message,
                                _system1_deferred=not response.break_loop)
        except (AttributeError, TypeError):
            pass
        try:
            self.agent.hist_add_warning(warning)
        except Exception:
            # The final-answer guard must not depend on warning UI availability.
            pass
