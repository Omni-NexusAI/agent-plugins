# Looped Mode verification record

What has been verified, where, and what has not. Update this when a claim
changes; do not list a path as verified without running it.

## Verified

### Unit tests (host, no Agent Zero)

`python -m unittest discover -s portable/looped/tests -p "test_*.py"`: 124 tests
pass (Python 3.13, 2026-11-22).

- Core: step parsing (including a step whose earlier fields are damaged) and
  canonical keys, programmatic checks, settings merge, modes, checkpoints,
  budget, agreement and tie-break, merged final answers, reason-twice,
  think-when-unsure with and without earlier passes carried forward, re-read,
  retry arming, parallel planning, counters.
- Adapter, against a copy assembled outside the monorepo with host fakes: both
  result shapes (tuple and `LLMResult`), native function calls passed through,
  background and unmarked calls ignored, manual arm lifecycle, per-chat mode,
  subordinates, prompt list not mutated, rejected sampling overrides retried,
  model failures contained, parallel early pass started, reused and cancelled,
  an unsure quick pass asked once more with the reasoning options added,
  carried passes reaching the reasoning call and cut-off notes a quick one,
  `/looped` parsing and the backend command hook.
- Packaging: `default_config.yaml` and the settings page defaults equal the
  core defaults; the assembled package is self-contained and compiles.
- Benchmark: task generation and splits, scoring, statistics, the dry run, the
  live-model gate's refusals (including waking a sleeping model only when no
  other model is held, reading a router's `/status` reply, and the in-use
  warning), stopping on a dead server with rows kept, the shared first pass,
  kept replies reused by a later run (a reasoning reply over the limit counted
  as cut off), the reasoning-on arm, the `carry` arm, and counting malformed
  replies apart from wrong answers.

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

### A second model with real wrong answers (MMLU-Pro): no strategy beat `plain`

2026-11-21, the local router's `ornith-1.5-35b-gpukv-128k-vision` preset
(Ornith-1.5-35B-A3B, split across an RTX 3060 and an RTX 3070, temperature
0.2). It was chosen by the owner in place of the 27B preset; no other model was
loaded, so nothing was displaced.

Calibration on `dev` questions, `plain` only, chose one setting. With reasoning
on, the model spent about 2,500 tokens per question and 3 of 5 replies were cut
off at `--max-tokens 3000`. With `--thinking off` it answered in about 9 s and
got 6 of 10 right, 3 of the misses being valid wrong steps. Reasoning off was
used, because it gives the wrong answers a second look is supposed to catch.

Main run: all 120 `heldout` questions, all five arms, `--thinking off`,
`--share-first-pass`, `--max-tokens 3000`, `--pause 1`. No request failed.
(The saved result's title says "dev split": `--split` does not apply to
question files and the title has since been corrected.)

| Arm | n | Accuracy | 95% CI | Fixed | Broke | p vs plain | Malformed | Calls/task |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| plain | 120 | 70.8% | 63.3% to 79.2% | - | - | - | 11 | 1.00 |
| reread | 120 | 70.8% | 62.5% to 79.2% | 13 | 13 | 1.00 | 16 | 1.00 |
| agree | 120 | 74.2% | 66.7% to 81.7% | 4 | 0 | 0.125 | 5 | 2.12 |
| deepen | 120 | 70.0% | 61.7% to 77.5% | 3 | 4 | 1.00 | 8 | 2.00 |
| stack | 120 | 72.5% | 64.2% to 80.8% | 11 | 9 | 0.82 | 4 | 2.15 |

**Correction (same day): this table over-counts unusable replies.** The
benchmark's parser was stricter than Agent Zero's. On this model most replies
counted under "Malformed" are complete steps that end with the right
`tool_name` and `tool_args` but carry damage earlier (an unclosed `thoughts`
list, a stray brace, a LaTeX backslash). A fresh `plain` sample of the same 120
questions had 16 such replies; Agent Zero's own parser
(`helpers/dirty_json.py`) reads the intended tool call in all 16. The parser
now reads them too (`core.salvage_step`), and with it that sample scores 89 of
120 with no unusable reply, against 78 with the old parser. So in this table
`plain` is understated, and every "fix" that replaced an unusable reply would
not happen inside a real agent. The raw replies of this run were not kept, so
it cannot be rescored; the next section repeats the comparison with the
corrected parser. The first model's results stand: its misses were empty
replies and bare letters, which Agent Zero also rejects.

`plain` was right 85 times, gave a valid wrong step 24 times and an unusable
reply 11 times, so unlike the first model this one leaves reasoning errors to
fix. How to read the rest:

- **No arm differs detectably from `plain`.** A run of 120 can only show a
  difference of roughly ten points or more.
- **`agree` never broke a right answer, and corrected 1 of 24 wrong ones.** Its
  other three fixes replaced an unusable reply. The second pass repeated the
  same wrong answer 13 times, was unusable 4 times and disagreed 7 times; of
  those 7 the tie-break reached the right answer once. It also disagreed with a
  right first answer 7 times and the right answer was kept every time.
- **`deepen` never corrected a wrong answer and broke 4 right ones.** It
  revised 10 steps: 3 unusable ones became right, 4 right ones became wrong, 3
  wrong ones stayed wrong. This matches the anchoring concern that made it
  experimental.
- **`reread` is noise on this model:** 13 fixed, 13 broken, and more unusable
  replies (16 against 11). It sends a different prompt, so it cannot share the
  first pass; 18 valid answers differed from `plain`, which shows how much a
  fresh sample moves at temperature 0.2.
- **`stack` inherits that noise** (11 fixed, 9 broken) at more than twice the
  calls.

Limits: one model, reasoning off, 120 questions, one run, and the parser
problem described above.

### Same model, corrected parser: reasoning on, and think-when-unsure

2026-11-21, same preset and the same 120 `heldout` questions, with the
corrected parser. `plain` and `think` (one call with reasoning on,
`--think-max-tokens 10000`, calibrated on 6 `dev` questions) were sampled once
and kept with `--replies`; `agree` and `escalate` then ran on top of those
replies, so all four arms share one first pass and `escalate` uses the same
reasoning replies as `think`. No request failed.

| Arm | Right of 120 | Accuracy | Fixed | Broke | p vs plain | Unusable | Calls/task | Tokens generated | vs plain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| plain | 89 | 74.2% | - | - | - | 0 | 1.00 | 28,977 | 1.0x |
| agree | 91 | 75.8% | 3 | 1 | 0.63 | 0 | 2.19 | 67,472 | 2.3x |
| escalate | 95 | 79.2% | 7 | 1 | 0.07 | 0 | 2.19 | 147,396 | 5.1x |
| think | 95 | 79.2% | 13 | 7 | 0.26 | 9 | 1.00 | 209,780 | 7.2x |

Tokens are completion tokens for everything an arm needs, including the first
pass and, for `escalate`, the reasoning calls it made.

- **Reasoning on every question** fixed 13 of the 31 misses and broke 7 right
  answers. All 9 unusable replies ran to the 10,000-token limit without
  answering (3 of them on questions `plain` had right). Half the replies took
  under 500 tokens; the long ones carry the cost.
- **`escalate` reached the same accuracy with about 70% of those tokens and
  broke one right answer instead of seven.** The second quick pass agreed with
  the first on 97 questions, which were left alone (83 right, 14 wrong both
  times). The other 23 were asked again with reasoning on: 7 misses became
  right, 6 kept the same wrong answer, 4 of the reasoning replies ran out of
  tokens (the quick answer stood), and of 6 right answers sent for reasoning
  one became wrong. Those 5 runaway replies (4 misses and 1 right answer) are a
  third of the arm's tokens.
- **`agree`** on the same disagreements fixed 3 and broke 1: a third quick
  sample is a weaker tie-break than reasoning.
- **What `escalate` cannot reach:** the 14 misses where the model gave the same
  wrong answer twice. Reasoning on every question fixed 6 more misses than
  `escalate` did, and paid for them with 6 more broken answers.

`escalate` was designed after the earlier run on these same questions, so the
table above is not a clean held-out result. The check on unseen questions:

**Confirmation on 90 questions not used before** (the `dev` file minus the 30
calibration questions; same settings, `plain`, `think`, `escalate`; no request
failed):

| Arm | Right of 90 | Accuracy | Fixed | Broke | p vs plain | Unusable | Calls/task | Tokens generated | vs plain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| plain | 62 | 68.9% | - | - | - | 0 | 1.00 | 20,860 | 1.0x |
| escalate | 65 | 72.2% | 5 | 2 | 0.45 | 0 | 2.28 | 141,492 | 6.8x |
| think | 64 | 71.1% | 7 | 5 | 0.77 | 5 | 1.00 | 136,468 | 6.5x |

- **The direction held; the size did not reach significance.** Three more
  right answers on 90 questions is well inside chance on its own.
- **The token saving over `think` did not hold.** Here 25 of 90 questions went
  to reasoning (23 of 120 before) and 5 of those ran to the token limit, so
  `escalate` cost as much as reasoning on every question.
- **What held on both sets:** `escalate` breaks fewer right answers than
  reasoning on every question (3 against 12 over the 210 questions) and never
  leaves an unusable reply (0 against 14), because a reasoning reply that runs
  out of tokens falls back to the quick answer.

Both sets together, for description only (the first set is not unseen): `plain`
151 of 210 (71.9%), `escalate` 160 (76.2%; 12 fixed, 3 broke, p = 0.035),
`think` 159 (75.7%; 20 fixed, 12 broke, p = 0.22); tokens 5.8x and 6.9x `plain`.

Runaway reasoning is the main cost: 10 of the 48 reasoning calls `escalate`
made hit the 10,000-token limit without answering, which is over half of its
reasoning tokens. Estimated from the kept replies (a reply longer than the
limit would have been cut off and the quick answer kept), a 4,000-token limit
would give `escalate` 159 of 210 at 4.2x `plain`. That is an estimate from
these same replies, not a measurement.

Limits, and why this is a modest, not a verified, improvement:

- Roughly four points of accuracy for five to seven times the tokens, on one
  model, one run per set, one-step multiple-choice questions.
- Significant only when the unseen and the seen set are pooled.
- The benchmark drives the core; `escalate` has not run inside Agent Zero with
  a real model, where the reasoning call goes through `reasoning_params`.

### Same model: carrying earlier passes forward did not help

2026-11-22, same preset, both question sets (210 questions), `plain`, `think`,
`escalate` and `carry` with `--think-max-tokens 4000`. `plain` and `think` came
from the kept replies (a kept reasoning reply over 4,000 tokens counts as cut
off). The second quick pass was sampled once in this run and shared by
`escalate` and `carry`, so both sent the same 48 questions to reasoning and
differ only in what `carry` adds: the two quick attempts shown to the reasoning
call, and one quick call that answers from the notes of a reasoning reply that
ran out of tokens. No request failed.

| Arm | Right of 210 | Accuracy | Fixed | Broke | p vs plain | Unusable | Tokens generated | vs plain |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| plain | 151 | 71.9% | - | - | - | 0 | 49,837 | 1.0x |
| think | 154 | 73.3% | 16 | 13 | 0.71 | 26 | 233,032 | 4.7x |
| escalate | 159 | 75.7% | 11 | 3 | 0.06 | 0 | 210,774 | 4.2x |
| carry | 154 | 73.3% | 10 | 7 | 0.63 | 0 | 249,964 | 5.0x |

By set: `escalate` 65 of 90 and 94 of 120; `carry` 65 of 90 and 89 of 120.

- **`carry` against `escalate` on the 48 questions sent to reasoning: 3 gained,
  8 lost (p = 0.23), for about 19% more tokens.** Not a significant loss, and
  no sign of a gain: level on the unseen set (2 gained, 2 lost), behind on the
  other (1 gained, 6 lost).
- **Showing the reasoning call the two attempts** (the 27 questions where its
  reply finished): `carry` 11 right, `escalate` 14, `plain` 8. The note did not
  make the reasoning side with an attempt more often (17 of 27 answers matched
  one of the two attempts, against 24 of 32 without the note), and it did not
  shorten the reasoning: 21 of 48 replies ran out of tokens with the note, 16
  of 48 without.
- **Answering from cut-off notes** (21 questions): 4 right afterwards, the same
  as the quick answer it replaced (2 fixed, 2 broken). 16 of the 21 answers
  were an option neither quick pass had chosen, and 15 of those were wrong.
  These questions cost 92,477 tokens, over a third of the arm's total.
- **The 4,000-token limit, now measured:** `escalate` 159 of 210 at 4.2x
  `plain`, which is what the estimate above gave (with a newly sampled second
  pass, so not the same passes as the 160 at 5.8x under the 10,000 limit).
  Reasoning on every question does worse under the lower limit: 154 right and
  26 unusable replies, against 159 and 14.

Limits: one model, one run, one-step multiple-choice questions, where a later
pass has little earlier work to build on. Multi-step tasks, where a looped
model's carried state is reported to matter, are not in the benchmark, so this
result does not cover them. `carry` stays off and experimental.

## Not verified

- **Better reasoning on any real model.** Two models have been measured. On
  the first, strategies only replaced unusable replies. On the second, which
  does give valid wrong answers, `agree` corrected few of them and `deepen`
  made valid answers worse. The experimental `escalate` gained about four
  points over `plain` (160 of 210 against 151) and matched reasoning on every
  question while breaking fewer right answers, but on the 90 unseen questions
  alone the gain is within chance, and it costs five to seven times the
  tokens. Carrying earlier passes forward (`carry`) added nothing to it on
  the same questions. The comparison with SenseNova-Loop-9B has not been run.
- **Multi-step tasks.** Every benchmark task is one agent step. Whether any
  strategy, `carry` included, helps over a task of several dependent steps has
  not been measured.
- **`escalate` and `carry` inside Agent Zero.** Unit-tested against host fakes
  only: not run in the container project, and not with a real model whose
  reasoning is switched by `reasoning_params`. Their settings toggles have not
  been opened in a browser.

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
