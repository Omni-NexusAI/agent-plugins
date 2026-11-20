# Looped Mode verification record

What has been verified, where, and what has not. Update this when a claim
changes; do not list a path as verified without running it.

## Verified

### Unit tests (host, no Agent Zero)

`python -m unittest discover -s portable/looped/tests -p "test_*.py"`: 95 tests
pass (Python 3.13, 2026-11-20).

- Core: step parsing and canonical keys, programmatic checks, settings merge,
  modes, checkpoints, budget, agreement and tie-break, merged final answers,
  reason-twice, re-read, retry arming, parallel planning, counters.
- Adapter, against a copy assembled outside the monorepo with host fakes: both
  result shapes (tuple and `LLMResult`), native function calls passed through,
  background and unmarked calls ignored, manual arm lifecycle, per-chat mode,
  subordinates, prompt list not mutated, rejected sampling overrides retried,
  model failures contained, parallel early pass started, reused and cancelled,
  `/looped` parsing and the backend command hook.
- Packaging: `default_config.yaml` and the settings page defaults equal the
  core defaults; the assembled package is self-contained and compiles.
- Benchmark: task generation and splits, scoring, statistics, the dry run, and
  the live-model gate's refusals.

`python portable/looped/assemble.py --check`: current.

### Real Agent Zero, isolated container project

`portable/looped/testenv/run_tests.ps1`, 2026-11-20. Host: Agent Zero v2.15
from the local `agent0ai/agent-zero:latest` image (created 2026-11-01), started
fresh on an internal network with a scripted stub model. 13 of 13 checks pass:

| Check | Observed in the running agent |
| --- | --- |
| 01 agree | Two passes agreed; the shell command ran once; timeline step "both passes agree"; the extra pass was unstreamed with its own seed; task re-read present in the prompt. |
| 02 tiebreak | Passes disagreed; a third decided; only the winner's command ran (the loser's computed marker never appeared). |
| 03 invalid first | A malformed first pass was replaced by a valid second, which ran. |
| 04 auto skips | Auto mode with only the risky-tool checkpoint made no extra call for a plain answer. |
| 05 auto risky | Auto mode checked the shell command and not the final answer. |
| 06 fuse | Two long, different final answers were merged in one extra pass. |
| 07 slash arms | `/looped message` armed one turn in manual mode; the token did not reach the model; the next message was not checked. |
| 08 slash mode | `/looped auto` set the chat's mode without running the agent. |
| 09 after error | A failing shell command armed a second look at the next step, with the retry note in the prompt. |
| 10 off | Mode off: no extra calls, no timeline step, no re-read, and `/looped` still stripped. |
| 11 reason twice | Experimental: the second pass saw the draft and its revision ran; the draft did not. |
| 12 parallel planning | Experimental: two tool-free plans plus a merge; the merged note reached the prompt. |
| 13 API and assets | Per-chat mode API (get, set, arm, command, reset, bad mode rejected), metrics API, and the settings page and composer files are served. |

Isolation during those runs: the 12 other containers on the machine, including
the live `agent-zero-latest`, were unchanged before and after; no host port was
published; the model server was never contacted.

### Benchmark pipeline

`python portable/looped/bench/run_bench.py --dry-run` produces the full table
for every suite and arm with a simulated model. Those numbers are not evidence
about any real model.

## Not verified

- **Any real model.** No strategy has been measured on a real model yet, so
  there is no evidence so far that Looped Mode improves results. The comparison
  with SenseNova-Loop-9B has not been run.
- **Browser rendering.** The settings page, the composer button and the
  composer-side `/looped` handling are served correctly but have not been
  opened in a browser. The test network publishes no port.
- **Agentspine `development` (v0.9.9).** The tuple-returning hook path is
  covered by unit tests with fakes only; no Agentspine container was available.
- **Built-in command picker on v2.15.** `commands/looped.command.yaml` has not
  been exercised; `/looped` was verified through the backend hook.
- **Parallel execution against a real multi-slot server.** Unit-tested only.
- **Chat apps (Telegram, WhatsApp), the message queue and the external API** as
  message sources for `/looped`.
- **Interaction with other plugins** that also replace the model result
  (for example System 1), and with the memory and infection-check plugins,
  which are switched off in the test container.
