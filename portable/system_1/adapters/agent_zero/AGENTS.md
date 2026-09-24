# Agent Zero package DOX

This directory is assembled into `plugins/system_1`. Agent Zero hooks, UI, and
API routes live here; the embedded `helpers/system_1_core/` is copied from the
portable core. Do not edit the assembled package directly. Run `assemble.py`
and compare its output. The host retains execution authority, embedding vectors,
and intervention handling.

The Main timeline uses `before_main_llm_call` to create one native Info step
per eligible System 1 decision; `helpers/timeline.py` updates it after routing.
The `hist_add_tool_result` extension observes only a pending System 1 action's
host-recorded result, masks it with the host secrets manager, then the next
model iteration may make a bounded choice. It fails closed if masking fails.
The result observer must never alter host history or block tool completion.
The action loop uses per-monologue state, an action count cap, and no replay of
action IDs. It withholds result content from the decision service unless the
action explicitly opts in, and returns observed content directly to the user
only with a separate action opt-in. Recheck both permissions and the exact
action definition immediately before the next decision. A guarded
`independent_while_main` action opt-in is required before System 1 may continue
dispatching a configured action while a background Main correction is pending;
the host remains the sole executor. Background advice may guide only a later
decision, after rechecking the request and action configuration. The guarded
`set_messages_after_loop` WebUI extension recognizes its `system1-main-` ID
and marks only that record with an S1
badge and accent. It must tolerate virtualized entries with no DOM element and
leave native Gen, Tool, and other Info records unchanged.
The `message_loop_end` hook closes a pending step if an interruption bypasses
the decision hook. Logging failures must not change model routing.
The Utility before-call hook may replace the model with a guarded fixed-response
wrapper only for an exact configured system/message pair and a high-confidence
finite decision. Preserve the original Utility model for every fallback and
the host callback contract. Utility metrics count all hook calls, decisions,
bypasses, and fallback attempts per agent and contain no
request or response text. The save hook validates route uniqueness, bounds,
and response choices, and removes the UI draft. Route prompts and fixed response
choices are sent to the configured decision backend only for an exact match;
oversized choices fall back to Utility. A decided fallback must not issue a
second decision before the original Utility call.
