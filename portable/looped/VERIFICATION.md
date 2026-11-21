# Looped Mode verification record

What has been verified, where, and what has not. Update this when a claim
changes; do not list a path as verified without running it.

## Verified

### Unit tests (host, no Agent Zero)

`python -m unittest discover -s portable/looped/tests -p "test_*.py"`: 102 tests
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
  other model is held, reading a router's `/status` reply, and the in-use
  warning), stopping on a dead server with rows kept, the shared first pass,
  and counting malformed replies apart from wrong answers.

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

### One real model: step format repaired, reasoning not tested

2026-11-20, `qwen3.8-flash-next-iq3_xxs-strata-mtp-vision-160k` on the laptop
Strata router (reached over Tailscale; one request at a time, 1 s pause after
each, about 10 s per request). The router ignores the thinking switch: the
model always reasons briefly before answering, so there is no thinking-off
condition and no matched-compute control here. Settings were the defaults,
fixed before the run; `heldout` split, seed 7.

| Suite | Arm | n | Accuracy | 95% CI | Fixed | Broke | p vs plain | Calls/task |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| arith | plain | 60 | 66.7% | 55.0% to 78.3% | - | - | - | 1.00 |
| arith | agree | 60 | 100.0% | - | 20 | 0 | < 0.001 | 2.00 |
| arith | stack | 60 | 100.0% | - | 20 | 0 | < 0.001 | 2.00 |
| arith | deepen | 60 | 100.0% | - | 20 | 0 | < 0.001 | 2.00 |
| arith | reread | 60 | 75.0% | 63.3% to 86.7% | 9 | 4 | 0.27 | 1.00 |

How to read it:

- **Every failure was a malformed step, none was a wrong answer.** All 20
  `plain` misses and all 15 `reread` misses were a bare number instead of the
  JSON step, and the number was correct every time. Counting the number alone,
  every arm scored 60 of 60.
- **The second pass repaired every malformed step.** In `agree` the first pass
  was malformed 16 times and the second pass was valid each time; the second
  pass was itself malformed 3 times and the valid first pass was kept (`stack`:
  15 and 5). `deepen` rewrote 16 drafts into valid steps. No task ended with
  both passes malformed.
- **This is not evidence of better reasoning.** The model made no arithmetic
  error in any arm, so there was nothing for a second look to correct.
- **The failure is partly caused by the question wording.** `arith` ends with
  "Answer with the number only", which invites a bare number. `arith_chain`,
  which ends "Put just that number in the answer text", had no malformed step
  in 20 tasks.
- **In a real agent the gain is smaller than the table suggests.** Agent Zero
  already answers a malformed step with a format warning and asks again, so the
  task is not lost without the plugin. What the second pass changes there is
  that the bad step never reaches the history; whether that helps later steps
  was not measured.
- `reread` did not differ detectably from `plain` (p = 0.27), as expected for a
  model that reasons first.

Calibration on `dev`, `plain` only, used to choose the suites: `arith` 20 of 30,
`arith_hard` 25 of 30 (all misses again bare, correct numbers, apart from one
empty reply), `tool` 30 of 30, `tool_hard` 30 of 30, `arith_chain` 20 of 20.
The model is at its ceiling on every generated suite, so none of them can show
a reasoning gain for it; that needs harder questions (a real dataset subset) or
a weaker model. The tool suites and `arith_chain` were therefore not run on
`heldout`.

### Same model, harder questions (MMLU-Pro): still no reasoning effect

2026-11-20, same model and router. Questions: a fixed sample of MMLU-Pro
(ten-choice, 14 subjects) fetched with `bench/prepare_datasets.py`, seed 7.
Calibration on 30 `dev` questions, `plain` only, chose the set and the limits:
MMLU-Pro 16 of 30 at about a minute per request; GSM8K 29 of 30 (the miss was
"5.00" scored against "5", since fixed), so GSM8K is too easy for this model
and was not run further.

Main run: 60 `heldout` questions (every second one, all 14 subjects),
`--share-first-pass`, `--max-tokens 3000`, defaults otherwise. Only `plain` and
`agree` were run; the other arms and the other 60 questions were left out to
keep the run near two hours.

| Arm | n | Accuracy | 95% CI | Fixed | Broke | p vs plain | Malformed | Cut off | Calls/task |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| plain | 60 | 70.0% | 58.3% to 81.7% | - | - | - | 18 | 8 | 1.00 |
| agree | 60 | 78.3% | 68.3% to 88.3% | 5 | 0 | 0.06 | 12 | 9 | 2.00 |

How to read it:

- **The gain is not significant at this size** (5 fixed, 0 broken, exact
  McNemar p = 0.06), and it cost twice the calls.
- **Every `plain` miss was an unusable reply, not a wrong step.** 8 replies
  were empty because the model was still reasoning at the token limit, and 10
  were a bare letter instead of the JSON step (8 of those letters were right).
  All 42 valid steps were correct.
- **All five fixes replaced an unusable first reply with a valid second one:**
  three bare letters that were already right, and two cut-off replies whose
  second attempt finished and was right. One more cut-off reply was replaced by
  a valid wrong answer.
- **Agreement never changed a valid answer.** Whenever both passes were valid
  (32 questions) they agreed, so the tie-break never ran. On this model a
  second sample repeats the first; it does not catch reasoning errors.
- **The second pass is no more reliable than the first.** It was unusable 22
  times in 60 (first pass: 18). In 12 questions both were unusable and the
  miss stood; 5 of those held a correct bare letter.
- As before, Agent Zero would itself ask again after an unusable reply, so the
  gain inside a real agent is smaller than the table suggests.

What this suggests for the plugin, not yet built or tested: for this kind of
model the useful second look is a cheap format repair ("send that again as a
step") and a retry when a reply is cut off, not a second opinion.

## Not verified

- **Better reasoning on any real model.** Both runs above show unusable
  replies being replaced, nothing more. No strategy has been shown to turn a
  valid wrong answer into a right one on a real model: the one model measured
  either answers correctly or fails to answer. `deepen`, `reread` and `stack`
  were not run on MMLU-Pro. The comparison with SenseNova-Loop-9B has not been
  run.

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
