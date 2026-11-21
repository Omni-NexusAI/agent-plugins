"""Prompt text used by the strategies. Kept short: small models follow short prompts."""

REREAD = "Read the task again before deciding the next step:\n\n{task}"

FUSE = (
    "Two independent drafts of the final answer were written for this task.\n\n"
    "Draft 1:\n{first}\n\nDraft 2:\n{second}\n\n"
    "Write the single best final answer. Keep what both drafts agree on, resolve "
    "any contradiction by re-reading the task, and do not add claims that appear "
    "in neither draft. Reply in your usual JSON format using the `{tool}` tool."
)

DEEPEN = (
    "This is your first-pass draft of the next step. It has NOT been executed.\n\n"
    "{draft}\n\n"
    "Re-read the task and check the draft for mistakes: wrong tool, wrong or "
    "missing arguments, a skipped requirement. Then output the step you will "
    "actually take, in your usual JSON format. Keep the draft unchanged if it is "
    "correct."
)

RETRY_NOTE = (
    "The previous step failed. Before the next step, re-read the task and the "
    "error, and choose a step that addresses the cause instead of repeating it."
)

PLAN_SYSTEM = (
    "You are planning, not acting. Write a short numbered plan for the task: the "
    "concrete steps, in order, each one checkable. Do not call tools, do not "
    "write JSON, and do not solve the task."
)

PLAN_MERGE_SYSTEM = (
    "You are given independent plans for the same task. Merge them into one "
    "short numbered plan. Keep steps the plans agree on, keep a step only one "
    "plan has when it covers a stated requirement, and drop anything the task "
    "does not ask for. Output only the plan."
)

PLAN_NOTE = (
    "Plan merged from independent planning passes. Use it as guidance and "
    "adapt it to what the tools actually return:\n\n{plan}"
)
