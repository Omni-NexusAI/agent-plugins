## System 1 bounded handback
Use `system1_delegate` when Main has resolved the uncertain part of the current
task and a still-eligible, bounded choice should return to System 1. The
current System 1 handoff note lists action IDs that Main may delegate. Pass
one to eight of those exact IDs as `tool_args.action_ids`, for example:

{"tool_name":"system1_delegate","tool_args":{"action_ids":["listed_action_id"]}}

You may also provide `tool_args.goal`: a nonblank, single-line description of
the bounded decision Main needs, at most 1000 characters. For example:

{"tool_name":"system1_delegate","tool_args":{"action_ids":["listed_action_id"],"goal":"Choose the next eligible lookup needed to verify the recorded status."}}

The host masks the goal before retaining it in System 1 state or sending it to Decider. If masking
is unavailable, or the goal is malformed or too long, delegation is rejected.
The goal is guidance only, not evidence or authorization. It cannot supply tool
arguments, change the original task, bypass prerequisites or permissions, or
justify repeating a completed call. Changing the goal does not permit replay.

This does not run a tool by itself. Agent Zero validates the current request,
action limits, available tools, and permissions before System 1 chooses the
next action. Do not delegate a completed call or invent an action ID. If the
tool says delegation is unavailable, continue in Main and finish the task.
