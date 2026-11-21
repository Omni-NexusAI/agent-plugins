# Looped Mode DOX

## Purpose

Looped Mode spends extra model calls to look twice at an agent's steps, for
models without a looped (recurrent-depth) architecture. It is a set of
test-time-compute strategies, not an emulation of a looped model: it re-reads
text, while a looped model deepens each token. The benchmark decides which
strategies earn their cost.

## Ownership

- `core/` owns framework-independent logic: candidate parsing and canonical
  keys, programmatic checks, mode/checkpoint/budget control, the strategies,
  prompts, sampling variants, and counters. It imports no host framework.
- `adapters/agent_zero/` owns Agent Zero hooks, the `/looped` command, per-chat
  mode, the settings page, the composer control, and the API handlers.
- `assemble.py` builds `../../plugins/looped/` from the adapter plus a copy of
  `core/` at `helpers/looped_core/`. Never edit `plugins/looped/` by hand.
- `tests/` owns core tests and adapter tests against an assembled copy.
- `testenv/` owns the isolated container test project and its guards.
- `bench/` owns the benchmark harness that drives `core/` directly.
- `VERIFICATION.md` records what has been verified, where, and what is open.

## Contracts

- The assembled package runs without this source tree. Adapter code imports the
  core only as `.looped_core`.
- Only the host executes tools. A step is resolved to exactly one whole
  candidate before the host parses it, so no tool runs twice. A tool call is
  never synthesised from two candidates; only final answers may be merged.
- Programmatic checks run before any model-based choice. A candidate that fails
  to parse, names an unknown tool, or repeats the last response cannot win
  against a valid one.
- A step whose earlier fields are damaged still counts as a step when the tool
  name and a well-formed `tool_args` object are the last thing in the reply
  (`core.salvage_step`), because Agent Zero's own parser reads such a reply.
  The adapter tries the strict parse, then the host's parser, then the salvage.
- Extra passes are lazy: the host's own call is candidate A, and further calls
  happen only at a checkpoint and within the per-step and per-turn budget.
- Every hook contains its own errors. A looped-mode failure leaves the host's
  original step in place.
- Extra calls copy the prompt list (the host wrapper mutates the list it is
  given) and never stream into the chat.
- Background calls, subordinate agents (unless `apply_to_subordinates`), and
  native function-call results (Responses transport) pass through untouched.
- Traces, timeline steps and metrics hold tool names, counts and timings only:
  no prompt text, tool arguments or credentials.
- Saved settings may be partial or a full replacement; `core.merge_config`
  fills gaps, keeps unknown keys and clamps bad values. `default_config.yaml`
  and the settings page's `DEFAULTS` literal must equal `core.config.DEFAULTS`
  (tests enforce both).
- `deepen`, `escalate` and `plan_branch` are experimental and ship disabled.
  A step is resolved by one of `deepen`, `escalate`, `agree`, in that order of
  precedence.
- `escalate` reasons only when two quick passes do not agree. The host supplies
  the reasoning call (`StepContext.think`); the Agent Zero adapter builds it
  from `strategies.escalate.reasoning_params`, which a saved setting replaces
  whole. Without a reasoning call it behaves as `agree`.
- Per-chat mode lives in `context.data["looped_mode"]` (saved with the chat).
  The one-shot arm lives in `context.data["_looped_once"]` (never saved) and is
  cleared when agent 0's turn ends.
- `execution: auto` currently means sequential. `parallel` starts the second
  pass alongside the first only when every step is checked, and only helps when
  the model server has two or more slots.

## Supported hosts

- Agent Zero v2.15 (`call_chat_model_turn`, `LLMResult`, built-in `_commands`).
- Agentspine `development` v0.9.9 (`call_chat_model`, tuple result). Hooks for
  both are shipped; a host ignores the hook folder it does not have.

## Verification

- `python -m unittest discover -s portable/looped/tests -p "test_*.py"`.
- `python portable/looped/assemble.py --check`.
- Container behaviour goes through `testenv/` only (see its README): its own
  compose project, stub model, no GPU, and a warning gate before anything that
  could touch a live model.
- Record results in `VERIFICATION.md`; do not call an unverified path verified.
