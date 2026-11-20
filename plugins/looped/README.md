# Looped Mode for Agent Zero

Looped-architecture models run part of the network more than once per token.
Looped Mode gives any ordinary model a second look at the agent level instead:
it spends extra model calls at the points where a wrong step is costly.

It adds compute, not knowledge. Expect fewer wrong tool calls and malformed
steps, not new facts. It does not reproduce what a looped model does inside the
network, and its benefit on your model is something to measure, not assume.

## What it does

| Strategy | What happens | Default |
| --- | --- | --- |
| Agreement before acting | A second pass must propose the same tool call. If the two differ, a third pass breaks the tie. Only the winning call is executed, once. | On |
| Programmatic checks | A pass that is malformed or repeats the last response cannot win against a valid one. | On |
| Re-read the task | The current task is repeated at the end of the prompt. Skipped once the model is seen to reason before answering. | On |
| Merge final answers | Two long final answers that differ are merged in one extra pass. Short answers are voted on. | On |
| Second look after errors | After a tool fails, the next step is checked twice. | On |
| Reason twice | Draft a step, then re-answer with the draft in view. Replaces agreement while enabled. | Off (experimental) |
| Parallel planning | Independent plans are written without tools and merged into one guidance note for the turn. | Off (experimental) |

## Modes

- **Manual** (default): nothing happens until you arm a message.
- **Auto**: checks at checkpoints: the first step of a turn, before a tool with
  side effects, before the final answer, after a tool error, and when a step is
  malformed.
- **Always**: checks every step.
- **Off**: disabled, including `/looped`.

## Using it

- `/looped your message` or `your message /looped`: looped mode for that message.
- `/looped`: arm the next message.
- `/looped on|auto|manual|off`: set the mode for this chat (`on` means always).
- `/looped status`: show the chat's mode.
- The composer button cycles the chat's mode; `1x` arms the next message.

Each check adds a **Looped** step to the chat timeline saying what happened
(for example "both passes agree"). It lists tool names, never arguments or
prompt text.

## Cost

A checked step costs one extra model call, two when the passes disagree. The
default cap is 8 extra calls per turn. In Auto mode most steps are not
checkpoints, so the average stays well under 2x.

`Execution: parallel` starts the second pass alongside the first. It only saves
time when the model server has two or more slots; with one slot the calls queue.

## Limits

- Extra passes are not streamed and cannot be interrupted mid-call.
- Models using native function calling (Responses transport) are passed through
  unchanged.
- Subordinate agents are not checked unless enabled in settings.
- The re-read block is skipped for tasks longer than its size limit.

## Install

Copy this folder to `usr/plugins/looped` in your Agent Zero data directory and
enable it in the plugin list. Settings are under the plugin's settings page and
can be set per project and per agent.
