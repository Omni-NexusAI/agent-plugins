# Agent Zero package DOX

This directory is assembled into `plugins/system_1`. Agent Zero hooks, UI, and
API routes live here; the embedded `helpers/system_1_core/` is copied from the
portable core. Do not edit the assembled package directly. Run `assemble.py`
and compare its output. The host retains execution authority, embedding vectors,
and intervention handling.

The Main timeline uses `before_main_llm_call` to create one native Info step;
`helpers/timeline.py` updates it after routing. A guarded
`set_messages_after_loop` WebUI extension recognizes its `system1-main-` ID
and marks only that record with an S1
badge and accent. It must tolerate virtualized entries with no DOM element and
leave native Gen, Tool, and other Info records unchanged.
The `message_loop_end` hook closes a pending step if an interruption bypasses
the decision hook. Logging failures must not change model routing.
