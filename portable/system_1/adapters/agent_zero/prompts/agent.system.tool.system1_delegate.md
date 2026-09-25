## System 1 bounded handback
Use `system1_delegate` when Main has resolved the uncertain part of the current
task and a still-eligible, bounded choice should return to System 1. The
current System 1 handoff note lists action IDs that Main may delegate. Pass
one to eight of those exact IDs as `tool_args.action_ids`, for example:

{"tool_name":"system1_delegate","tool_args":{"action_ids":["listed_action_id"]}}

This does not run a tool by itself. Agent Zero validates the current request,
action limits, available tools, and permissions before System 1 chooses the
next action. Do not delegate a completed call or invent an action ID. If the
tool says delegation is unavailable, continue in Main and finish the task.
