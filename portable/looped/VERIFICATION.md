# Looped Mode verification record

What has been verified, where, and what has not. Update this when a claim
changes; do not list a path as verified without running it.

## Verified

### Unit tests (host, no Agent Zero)

`python -m unittest discover -s portable/looped/tests -p "test_*.py"`: 98 tests
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
- Benchmark: task generation and splits, scoring, statistics, the dry run, the
  live-model gate's refusals (including waking a sleeping model only when no
  other model is held), and stopping on a dead server with rows kept.

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

  Two live attempts were made on 2026-11-20 against the local router's
  `swift-1.5-qwen38-27b-stream-200k-vision-mtp` preset (Qwen3.8-27B Q4_K_S,
  split across an RTX 3060 and an RTX 3070, thinking off, temperature 0.7, one
  request at a time, about 3.5 s per request). Both ended the same way: the
  RTX 3060 dropped out (`nvidia-smi`: "GPU is lost", reboot needed), after
  about 28 minutes of back-to-back requests the first time and about 11 minutes
  the second. The second run logged the card every 30 s: it peaked at 59 C and
  152 W, so heat is not the obvious cause. Whether the benchmark's sustained
  load is the trigger is not established, but it was the workload both times.
  **Do not start a third run on this preset without the owner's decision.**

  What was measured before the second failure (arithmetic, `dev` split as it
  was then: only two of the four question types):

  | Arm | Tasks | Accuracy | 95% CI |
  | --- | ---: | ---: | --- |
  | plain | 100 | 75.0% | 66% to 83% |
  | reread (same 81 tasks: plain 74.1%) | 81 | 79.0% | 70% to 88% |

  Re-read fixed 15 and broke 11 of those 81 (exact McNemar p = 0.56): no
  detectable effect. About a third of answers flipped between two single
  samples, so sampling noise at temperature 0.7 is larger than any effect
  this size of run could show. `agree`, `stack`, `deepen`, the thinking-on
  control and the tool-choice suite were not measured. The first attempt's
  three finished arms were lost, because the harness then saved only at the
  end; it now saves each row as it finishes and stops after three failed
  requests in a row.
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
