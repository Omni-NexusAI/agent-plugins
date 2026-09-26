# System 1 local verification

This record describes the Agent Zero test instance used for the System 1 expansion. It contains aggregate outcomes and tool names, not prompts, credentials, or raw MCP responses. The test instance reuses one existing task-owned container; each comparison snapshots and restores its plugin and memory settings.

## Implemented checks

- The portable Python suite and assembled Agent Zero package are checked together. The package must import without the monorepo. The current revision has 203 passing focused tests and 44 assembled files; the updated package has been installed in the existing Agent Zero test container for live checks.
- Agent Zero remains the executor for native and MCP tools. System 1 selects bounded actions; later decisions consume host-recorded results. Main writes the final answer when the evidence needs prose.
- Utility direct memory-query and bounded relevance choices are eligible only for verified host call shapes. Unknown, changed, failed, or uncertain calls use the complete original Utility call. Embedding mode does not replace vectors or the index.
- The plugin settings page and S1 timeline were inspected in the rendered host UI at desktop and narrow widths. The shared Decider card used adjacent native model field styles and fit the narrow modal; S1 steps expanded beside unchanged Gen and MCP records at both widths. After the final package update, opening the plugin settings moved keyboard focus into the modal, and reverse Tab from the close button wrapped to Cancel instead of reaching the background list. Invalid action JSON displayed a field error, blocked Save, and kept focus in the field; Cancel then reopened with the original valid value and initial focus on the first select. A temporary unreachable Decider endpoint made the rendered status show `unavailable`; after automatic config restoration, Check connection showed the disabled-button `Checking…` state followed by `available`. The temporary viewport override and inspection tabs were removed afterward.

## Practical Main evidence

### Dynamic task control on the current local build

The live Jev checks below used the existing test instance, its connected GitHub MCP (26 tools), and read-only native tools. Each trial restored the saved System 1 settings. They are bounded examples, not estimates of general task success or speed.

| Path | Recorded result | Complete request time |
| --- | --- | ---: |
| Uncertain Main work with independent actions | Main owned the uncertain comparison while Agent Zero started native parallel skills and GitHub status jobs, collected their results, and produced a substantive answer. Both child calls appeared once. | 46.27 s |
| Main delegates back to System 1 | System 1 ran the native skills search; Main called `system1_delegate` once; System 1 then selected a separate GitHub PR-status lookup. Agent Zero recorded each action once, and Main wrote the final skills and CI answer. | 58.92 s |
| Independent parallel calls | One native parallel batch contained skills search and GitHub PR status; each child result was recorded before Main's complete answer. | 48.73 s |
| Dependent sequence | GitHub PR status and skills search were independent parallel children. A later README read used the exact commit SHA in the recorded status result and was not batched with its prerequisite. Each child and dependent read appeared once. | 39.52 s |
| Failed MCP read | One missing-file lookup failed; the S1 timeline marked failure, and Main answered that the file was unavailable without retrying the call. | 32.84 s |

The Main-to-System-1 handback was also tried with an earlier, less specific prompt. Jev declined the bounded PR-status choice, and Main reported that it had not run; that trial does not count as a successful handback. The completed handback above used a prompt that explicitly requested both the skills and CI facts. This demonstrates that the return path works while retaining Jev's ability to decline an action.

In a single like-for-like PR lookup, Main-only completed in 27.30 s and System-1-on completed in 17.64 s. Both made one GitHub call and passed the same bounded answer checks. One pair cannot establish a repeatable speed gain. Unit regressions cover Main-owned parallel child replay prevention, mixed success and failure, malformed collection, low-confidence and stale handback, and native error text inside a successful parallel envelope; those cases are not all live host proofs.

The dynamic build was also rechecked through the stable-corpus memory matrix: two full two-turn chats per mode, eight chats total. All eight completed and all bounded answer checks passed. Test-chat ingestion was disabled, and the FAISS and pickle index hashes were byte-identical before and after; both plugin and memory settings were restored. Utility-only made two Decider query decisions and bypassed 2 of 9 completed Utility calls (22.2%); both-on made two decisions and bypassed 2 of 10 (20%). Modes with Utility off bypassed none. The ambiguous follow-up retained normal Utility generation. Median complete two-turn time was 123.95 s both-off, 115.92 s Main-only, 151.32 s Utility-only, and 148.83 s both-on. The Utility-on cells took longer end-to-end in this run despite reducing measured Utility model time; with two repetitions per cell and wide ranges, there is no demonstrated speed gain. Decision time summed to 0.65 s Utility-only and 0.60 s both-on across their four turns, excluding overlapping stages.

An additional live Embedding-only memory query completed in 49.19 s and passed the bounded answer checks. It made one Decider guidance decision, bypassed zero Utility calls, left the selected embedding model configuration unchanged, and preserved byte-identical memory index hashes. Saved plugin and memory settings were restored.

The real GitHub MCP reported 26 connected tools. A repeated comparison used two read-only tasks, two repetitions each, under four mode combinations. All 16 requests produced complete answers that passed their bounded factual checks, and the expected host-recorded tool result appeared in each. System 1 selected the expected tool in all eight Main-on trials; Main selected it in the eight Main-off trials. No duplicate tool events appeared.

| Task | Both off, median (range) | Main only | Utility only | Both on |
| --- | ---: | ---: | ---: | ---: |
| GitHub pull request lookup | 32.94 s (27.52–38.36) | 24.68 s (23.22–26.14) | 27.52 s (27.47–27.58) | 23.36 s (21.92–24.80) |
| Native skills search | 23.59 s (22.22–24.95) | 19.99 s (19.91–20.08) | 26.63 s (23.80–29.47) | 21.75 s (16.27–27.23) |

The host's memory query-preparation and post-filter flags were off for this first comparison. Utility bypass was zero in every cell, so these timings do not demonstrate a Utility speed improvement. The small sample sizes also do not establish a general Main speed gain.

In a separate dependent GitHub task, System 1 selected a pull request status lookup and then a file read whose branch argument came from the prior host-recorded result. Agent Zero executed both. Main fetched missing pull request metadata and wrote a complete answer; five bounded factual checks passed, with no duplicate tool call. That run took 83.49 s. A Main-only control on the same task took 77.41 s and passed the same five checks. This single pair demonstrates functional multi-step behavior, not a speed win.

A mixed task requested Main advice for an open-ended comparison while System 1 selected one independent native skills lookup and one independent GitHub MCP lookup. In the first live run, the advice arrived and System 1 applied it, but normal Main repeated both calls five more times each and failed to finish within 180 s. A bounded foreground Main handoff note was added; it points to the host's recorded results without copying their contents, arguments, prompt, or credentials. In the rerun, System 1 selected and observed each lookup once, Main's correction was applied, and no duplicate lookup occurred. Main eventually produced a substantive final answer that passed five bounded factual checks, about 194 s after the start. The test client's 180-s request deadline expired before that answer arrived, so this is a late host completion, not an HTTP completion or a speed win. The long Main generation time needs separate performance assessment.

The shorter mixed task had one low-confidence first attempt: Jev chose an eligible action at 47% against a 50% threshold, so System 1 handed the task to Main. Main completed it in 30.49 s with seven bounded content checks passing, but this did not exercise the correction path. The timeline detail was then corrected to name the confidence threshold instead of incorrectly saying no action was eligible. On a second live attempt with the same three configured read-only actions, System 1 selected and observed a native skills lookup and GitHub PR-status lookup while Main advised in the background. After the correction, System 1 selected a GitHub README read with its branch bound to the validated 40-character SHA in the earlier status result. Agent Zero recorded all three tool results once each; Main wrote a complete answer passing seven bounded content checks in 32.50 s. The background Main span was recorded once (14.64 s), foreground Main once (4.87 s), and the index hashes and saved plugin/memory settings were unchanged after the run. The test demonstrates one correction-shaped subsequent action, not a general performance gain. In the first short attempt, four tool result events and three aggregate tool-timing spans were observed; aggregate counters cannot attribute the missing span to a particular action, so that duration remains unavailable.

For a live backend-failure case, the test instance temporarily selected an unreachable decision endpoint. System 1 recorded `Decision unavailable` and handed off to Main; Main made one real GitHub PR lookup and returned an answer passing three bounded checks in 18.34 s. No System 1 action was submitted, and the original Decider and memory settings and index hashes were restored. A strict-confidence Utility case made one Decider decision, bypassed no Utility call, and used the complete original Utility fallback call; its answer passed three bounded checks in 22.67 s. These checks establish fallback behavior, not relative speed.

## Memory and performance gates

The first memory diagnostic completed seven of eight full chats; one timed out. It found zero Utility decisions because the live host's first-turn history shape was outside the initial parser. The corrected host bootstrap exception was then tested with the actual Utility model disabled for one eligible call: a Utility-only chat produced a complete answer, Decider made one direct-query decision, and one of two completed Utility calls was bypassed. This single case demonstrates a working Utility-only path, not a speed improvement.

A subsequent four-mode memory comparison ran two repetitions per mode, each with a self-contained request followed by an ambiguous follow-up. All 16 answers passed the same bounded checks. With Utility mode on, all four eligible first-turn queries used Decider and bypassed the original Utility call. None of the ambiguous follow-ups bypassed Utility. In the Utility-only cells, 2 of 14 completed Utility calls were avoided (14.3%); with both modes on, 2 of 13 were avoided (15.4%). Both modes off and Main-only avoided none. Median complete two-turn time was 60.32 s both off, 49.64 s Main-only, 45.66 s Utility-only, and 60.22 s both on, with just two repetitions per cell. The host memorized test chats during this run, and the index hash changed. The searchable corpus was therefore not held constant: these timings are observational and establish no speed gain. Saved System 1 and memory settings were restored after all eight chats.

After stage instrumentation was installed, a further Utility-only two-turn task temporarily disabled test-chat ingestion. The FAISS and pickle index hashes remained identical throughout. The self-contained turn made one direct-query decision and bypassed its original Utility call; the ambiguous follow-up made no decision and retained three ordinary Utility generations. Both full answers passed their checks, and all settings were restored. This checks index preservation and Utility fallback, but is one mode and one task pair, not a complete controlled four-mode latency comparison.

A subsequent stable-corpus four-mode comparison ran two repetitions per cell, with the same self-contained memory request and ambiguous follow-up. The built-in memory query-preparation and post-filter flags were enabled in every cell; test-chat ingestion was disabled temporarily. All eight two-turn chats returned within the 300-second request deadline, and both the System 1 and memory configurations were verified restored. The FAISS and pickle index hashes were byte-identical before and after all trials. Utility-on cells made four eligible first-turn Decider query decisions and bypassed four original Utility calls; the ambiguous follow-ups made no Decider decisions. Utility-only and both-on each avoided 2 of 8 completed Utility calls (25%); both-off and Main-only avoided none. All eight first-turn answers passed bounded content checks. Seven of eight follow-ups passed the ambiguity check; one Utility-only follow-up was seven characters and failed that check. Median complete two-turn times were 113.32 s both off, 87.98 s Main-only, 78.88 s Utility-only, and 67.37 s both on. With two trials per cell, substantial timing variation, and the one answer-quality failure, these are observed times and **not a validated speed gain**. Stage hooks recorded prompt preparation, Main, Utility, Decider, and memory-recall spans; nested spans overlap and cannot be added to get wall time.

Prompt-to-final-answer wall time is measured for complete requests. Plugin metrics record Decider time, Utility model time, bypasses, and fallbacks where that path is active. The initial saved chat traces lack stage start/end measurements for prompt preparation, Main generation, native and MCP tool execution, and memory search. Those stages are reported as unavailable rather than inferred from total time. The later Utility-only task confirmed that the hook-based API returned nonzero counters for prompt preparation, foreground Main model calls, host tool execution, and the memory-recall hook span. The host schedules memory ingestion in background tasks, so these hooks do not measure index-write time. Delayed recall can outlive the measured hook span, and overlapping stage times must not be summed into wall time.

The memory index remained readable after test chat ingestion: FAISS loaded with 19 vectors of dimension 384, and a reconstructed vector found itself at finite distance. The index changed as the host ingested chats; there is no pre-run vector count, so this is an integrity check rather than proof that every write was append-only.

## Earlier hands-on preparation snapshot

- The final rendered settings and S1 timeline were rechecked after the last package update. The assembled package was imported in the existing test container, the focused suite passed, and the draft pull request was refreshed with the verified source.
- For hands-on use, the existing test instance has Main and Utility enabled, Embedding disabled, and memory query preparation and post-filter enabled. Three additional read-only test actions were configured locally: native skills search, GitHub pull-request status, and a README read bound to the observed status SHA. These action definitions and the lower read-only test confidence threshold are local test settings, not changes to the pull request or production configuration.
- A focused hands-on prompt used the status lookup followed by the SHA-bound README read. System 1 selected both actions, Agent Zero recorded each result once, Main wrote a substantive answer, and the HTTP request completed in 30 seconds. Saved System 1 and memory settings and the memory index were unchanged across this probe.
- A broader hands-on prompt added native skills search and an open-ended comparison. System 1 selected and observed all three actions once, with no Main-dispatched duplicate tool. Agent Zero logged two malformed Main responses and a repeated-response retry. The client timed out after 300 seconds, although the host later produced a substantive final answer. The test-chat memory index changed after that client deadline when the host completed delayed ingestion; that trial is not an index-preservation or latency success.
- The Utility-only ambiguous follow-up in the stable-corpus matrix remains an answer-quality failure. More completed, like-for-like trials are required before claiming reliable full-task speed gains, particularly for open-ended mixed prompts. The user's hands-on acceptance remains pending.

The browser, desktop-control, image-capable, and local alternative backend evaluations are later work.

## Proposed-tool and wait visibility follow-up

A live Jev probe in the existing test instance temporarily raised Main's
confidence threshold to 100% for one read-only GitHub PR-status action. Jev
proposed `github_mcp_server.get_pull_request_status` at 99% confidence. The S1
handoff step named it under **Proposed tool**, without claiming that System 1
executed it; Main subsequently used host tools to answer. The request
completed, and the saved plugin settings were restored exactly. Handoffs with
no proposed tool now explicitly display `None`. The focused Python suite
passed after this change.

The Main timeline also records a `System 1 waited for Main` step when Jev
chooses to await Main despite independent actions being offered. It reports
the count of policy-eligible alternatives and the actual wait duration. Those
alternatives still require task-relevance and dependency review before they
can be counted as missed action opportunities. Repeated live arrival-rate and
wait analysis remains to be run; no throughput conclusion follows from the
existing mixed-task trace alone.

For longer mixed-task comparisons, the per-chat metrics API now retains at
most 256 completed stage intervals relative to its first measurement and
reports how many older intervals were dropped. This allows actual Main
background/tool overlap to be computed rather than inferred from aggregate
seconds. The focused tests verify overlapping intervals and that no prompt
content is returned.

A single local coding-plus-retrieval turn completed in 138.95 s with Main
System One Mode enabled. System One submitted an independent native skills
search and GitHub PR-status lookup through Agent Zero; Main used the native
code tool, recorded a passing local `test_counter.py` check, delegated a
bounded README lookup back to System One, and returned a substantive final
answer. The first harness pass falsely marked the code check missing because
Agent Zero records code execution as `code_exe` rather than `tool`; it also
treated a harmless LF-to-CRLF rewrite of the test fixture as a content change.
Replaying the saved host trace after correcting those checks confirms the
code action and ordering; a separate sanitized replay report records the
source chat-file hash and corrected artifact checks. This is one live turn,
not a reliability or speed
claim. Relative stage intervals show two memory-recall spans near the host's
30 s timeout, and the chat timeline reports both recalls timed out. Utility
System One Mode was off in this coding trial. Saved settings and the memory
index were verified restored and unchanged.

A separate one-repetition matched memory-retrieval pair used the same saved
Default model preset and bounded search limits with Main System One Mode off.
Utility System One Mode on finished in 59.39 s and bypassed one query-writing
Utility call; mode off finished in 77.64 s. Both recall operations timed out
and returned no memories, so neither passed a retrieval-accuracy gate. Both
recorded about 29 s of ordinary Utility model generation, and the full-turn
difference was mostly Main foreground time. This pair does not establish a
memory speedup. Saved System One and memory settings were restored, and FAISS
and pickle index hashes remained unchanged.

After adding allowlisted Utility model-call category timing, another matched
single-turn pair used that same preset, corpus, and bounded limits. Utility
System One Mode on completed in 28.38 s, recalled three memories and two
solutions, and passed bounded answer checks; its Decider query choice took
0.37 s and the ordinary Utility memory-filter model call took 0.80 s. The
mode-off client request reached its 180 s deadline without a final answer;
at that point its recorded foreground Main time was about 139 s, while its
completed Utility model calls totaled 1.06 s in the saved deadline report.
The host continued the request and recorded a final response about 347 s
after the user message; a later read-only metrics snapshot then showed about
7.6 s of completed memory-query and filter model calls. The on trial recalled
three memories and two solutions; the eventual off trial recalled three and
three, so retrieved-item equality was not established. This pair is an
incomplete client control and does not prove a speed advantage. Both
settings objects were verified restored and the index hashes matched. The
host may continue processing a chat after the synchronous client timeout;
do not reuse that timed-out chat as a completed control result.

One post-review Utility-on diagnostic trial completed in 37.31 s with one
memory and two solutions recalled. Decider bypassed the direct query in
0.55 s; the remaining original Utility memory-filter call took 13.56 s, and
the measured memory-recall hook took 15.65 s. This identifies relevance
filtering as a material variable cost in that turn, but provides no matched
complete-task speed claim. Filter eligibility reason counters then identified
one real retrieved candidate exceeding the former 800-character per-candidate
cap. The cap was raised to 4000 characters without truncating candidate text;
the complete encoded decision remains bounded by `max_state_chars`. A live
41.13 s retrieval trial then reached the 4000-byte payload gate, and a 41.80 s
trial with the raised candidate cap also reached that gate. A temporary
8000-byte policy trial completed in 51.03 s but still exceeded the payload
gate. At the plugin's 16000-byte policy ceiling, two Utility-on trials
completed in 39.48 s and 44.05 s and reached the Decider. Both fell back to
the original Utility filter; the second trial's reason counter confirmed a
choice below the configured confidence threshold, with 0.85 s of added
decision time and 9.27 s in the original Utility filter. The earlier 16000-byte
trial did not record its fallback reason. All these are single, unmatched
diagnostics, not evidence of faster memory retrieval. Every trial restored
the saved System 1 and memory settings and preserved the FAISS and pickle
index hashes. Do not lower the confidence threshold or classify candidates
independently: the host's relevance contract compares candidates for conflicts,
duplicates, recency, and completeness.

## Matched long-turn coding comparison and output integrity

A two-repetition, lane-neutral coding/skills/GitHub comparison held the task,
models, memory configuration, and answer requirements constant. All trials
restored saved settings and preserved index hashes. The delivered results were:

| Repeat | Main only | Main with System 1 |
| --- | --- | --- |
| 1 | 369.74 s host completion; client reached its 300 s deadline; quality passed | 116.01 s; quality passed |
| 2 | 120.43 s; quality passed | 246.40 s; final-answer quality failed |

The second System 1 answer ended midway through a table and omitted the
requested README/portable summary. That summary reached Main through the
recorded README result and appeared in its full provider output. Main emitted
malformed response JSON; the host's tolerant parser split it into a shortened
`text` and stray sibling arguments, and the response tool delivered only
`text`. This is a real delivered-answer failure. Internal generated content
does not make the trial a quality pass. Repeated tool names were distinct
operations (skills search versus list, and two different delegation sets), not
same-argument replay. Neither the timing gap nor the raw internal output is a
validated speed gain.

These trials did not establish foreground Main coding concurrent with an
independently progressing System 1 loop: all recorded background Main spans
were zero, and retrieval/delegation followed coding. That overlap remains a
separate live acceptance gate.

The plugin completion hook now rejects successfully executed response calls
with unexpected arguments in the current System 1 monologue. It requests up
to two formatting retries using existing evidence, replaces the partial chat
bubble, and returns an explicit failure if retries are exhausted. A valid
singleton `text` or `message` passes unchanged. Missing/non-string content
remains the host's native response repair path. Pending parallel collection
takes precedence over formatting retries. Deferred records have private
nonterminal metadata; the live-test harness excludes them even when the host
marks the response log finished. Focused tests cover quoted/multiline text,
split fields, bounded retries, new-turn isolation, and pending-job precedence.
The next two-repeat comparison delivered complete answers and verified local
effects in all four trials (System 1: 130.42 s and 96.74 s; controls: 112.23 s
and 129.12 s). One malformed control response triggered the formatting guard:
turn state existed even with Main mode off. The source now additionally requires
Main System One Mode to be enabled; a regression covers existing state with
the mode off. Because that control received plugin intervention, this comparison
is not an untouched baseline and does not establish a speed improvement.
Saved settings were restored and memory index hashes were unchanged.

The reviewed async path now permits one or more already-selected independent
native/MCP children to start without waiting while foreground Main continues.
It requires exact root-agent/config identity, parent tool-policy approval, and
pinned native dispatcher sources. Unsupported children and unverified hosts
use ordinary dispatch. Unresolved receipts retain replay reservations and block
completion; trusted registry recovery supplies identities only. This does not
create an autonomous second tool loop. The assembled package passes 186 focused
tests. A controlled live probe recorded one nonblocking native batch containing
a delayed local read and a real GitHub status lookup. Foreground Main wrote a
local function and completed its actual assertions approximately 35 seconds
into the 90.01-second read. Both jobs were collected; the final useful answer
completed in 234.31 s, with no repeated GitHub calls. Saved settings were restored
and index hashes matched. Main's subsequent README delegation was declined by
System 1 (a `main` choice at 63% confidence); Main performed that lookup instead.
The initial harness counted the delegation attempt too loosely. Its corrected
gate now separately requires a System 1-selected, host-recorded, System
1-observed dependent action. Thus foreground overlap passed, while this full
handback scenario did not. A repeat uses an action description reflecting only
its actual recorded-SHA dependency, preserving code-before-delegation ordering.
The artificial read delay must not be counted as a speed benchmark. Rendered
S1 records and expandable handoff details were inspected at desktop (1280 px)
and narrow (390 px) widths alongside native Gen, Tool and MCP entries.

A second controlled overlap trial completed in 130.23 s and again passed the
actual coding-during-retrieval checks, final-answer checks, duplicate checks,
settings restoration and unchanged-index checks. It again declined the
dependent README handback, so the corrected combined acceptance gate failed.
Changing a truthful action description did not establish reliable handback.
An optional bounded, masked Main subtask goal now accompanies foreground
delegation. It supplies decision context only, never action authorization,
result evidence, argument values, or a new replay identity. The third live
trial supplied that goal and completed in 129.10 s. Actual coding overlapped
the retrieval, both GitHub calls occurred once, final-answer checks passed,
and settings and index hashes were restored. System 1 again declined the
dependent README choice; therefore the complete handback acceptance gate
still failed. A native chat-label API call also failed; the route was corrected
and the completed chat label subsequently verified through native save/get.

## Current open gates

- Goal-first delegation passed two foreground overlap tasks: System 1
  selected and observed the dependent README read after Main verified code and
  collected both independent jobs. Useful answers completed in 114.16 / 111.18 s;
  no GitHub call repeated, the native chat label was verified, and saved settings
  and default memory hashes matched in both trials. The
  artificial delay is an overlap test, not a latency benchmark.
- Matched native recall, filtering and full-chat answers now pass the bounded
  checks below. Timed-out recall cannot count as a speedup; broader workloads
  and automatic ingestion scheduling retain their separate verification boundary.
- The new isolated native memory harness checks known facts in a retained
  task-owned index. Awaiting a native ingestion coroutine is not proof of the
  host's automatic background scheduler completing its writes.
- Full-task speed comparisons require complete equivalent answers, unchanged
  model settings except the tested factor, and no intervention in the baseline.
- The draft PR must reflect the locally verified source before hands-on
  readiness is reported. User acceptance and merge authorization remain open.

## Known-fact native memory verification

A process-local configuration overlay used five controlled documents in a new,
retained native memory subdirectory. The corpus included current facts, an
outdated plan, an uninformative duplicate, a durable safety rule, and another
project. Every matched trial retrieved all five candidates and selected exactly
the current facts plus safety rule, with valid unique indices and no incorrect
facts. Native persistence and reload checks passed; the default index was never
initialized by the harness and its file hashes remained unchanged.

| Configuration | Native recall off | Native recall on | Observed mechanism |
| --- | ---: | ---: | --- |
| Saved Utility, 4000-character decision limit | 10.40 / 10.25 s | 3.05 / 4.75 s | Direct query bypass; filtering used Utility because the complete payload was oversized. |
| Alternate saved Utility name, same 4000 limit | 25.57 / 22.22 s | 8.16 / 15.38 s | Query bypass; filtering still used Utility. Models ran separately, so this is not a randomized model comparison. |
| Saved Utility, process-only 8000 limit | 6.65 / 4.83 s | 0.73 / 0.76 s | Both query and filtering bypassed Utility, preserving exact facts. |

Each row has two trials per mode, with alternating mode order. The last row
avoided four of four real Utility calls during its two native recall operations;
separate all-candidate relevance controls also selected the expected indices.
This is bounded component verification, not prompt-to-final-answer timing or a
general percentage of Utility work replaced. No saved model or decision-limit
setting changed during these process-only experiments.

Explicitly awaiting the native fragment-ingestion body persisted the known
support-contact fact and preserved the initial fixture. The solution-ingestion
body stored no solution: this history contained a user assertion rather than
an Agent-executed technical solution. Body return, persisted output, and error
indicators are separate checks. Automatic background scheduling remains a
different acceptance boundary; its log heading alone is not a write barrier.

## Full-chat memory comparison after filtering correction

The first eight real chats exposed a routing restriction: filtering reused the
32-word limit for direct query reuse. All answers were useful, but Utility-on
avoided no calls. Its first host load also imported six native built-in knowledge
documents into the task-owned index, preserving the original five fixtures.
That cold initialization and zero bypasses prevent attributing its timings to
System 1 acceleration.

Filtering now retains a complete validated current-user envelope independently
of the short direct-query heuristic. Query writing still falls back for this
46-word request; unknown envelopes and oversized complete payloads also retain
the original Utility call. The patched native host repeated eight labeled chats
against the initialized corpus, with identical models, prompt, answer criteria,
Embedding off, ingestion off, and a temporary 8000-character decision limit.

| Main mode | Utility mode | Client wall times through completion verification | Native recall times | Utility calls avoided |
| --- | --- | --- | --- | --- |
| Off | Off | 24.30 / 23.64 s | 7.93 / 6.97 s | 0 of 4 |
| On | Off | 28.44 / 25.25 s | 12.35 / 10.52 s | 0 of 4 |
| Off | On | 19.27 / 30.06 s | 3.28 / 3.35 s | 2 of 4 (50%) |
| On | On | 16.39 / 17.86 s | 3.77 / 3.93 s | 2 of 4 (50%) |

The client wall times include post-response source, configuration, idle and
metrics verification; they are not clean prompt-to-final-response latency.
These two-trial ranges describe this task only. Utility-on avoided relevance
generation in all four enabled turns; query generation remained ordinary Utility.
Each filtering decision added 0.20–0.25 s. Utility-only recall was consistently
shorter here, but its mean verified client wall time was slightly longer than
both-off. Both-on averaged 17.13 s versus 23.97 s both-off including verification
overhead, not a clean final-response speed or causal attribution claim. This no-action memory task
does not measure Main delegation performance; the separate overlap trials do.

All eight completed answers passed semantic review for current facts, safe
containment on health failure, and clear separation of superseded or unrelated
facts. One answer correctly named rejected historical values, causing the
simple string-exclusion check to fail; manual review confirmed they were not
presented as current. Every completion barrier passed. Both initialized fixture
and default index hashes remained unchanged, and original plugin, memory and
model settings were verified restored. The saved 4000-character limit was not
changed; larger filtering payloads can still fall back under that setting.

### Observed final-answer timing

A further eight matched chats separated lightweight final-response observation
from the full completion barrier. Timing starts immediately before message POST
and stops when persisted history first shows a finished, nondeferred task answer,
polled every 0.5 s. Source/configuration/idle/metrics checks run afterward for
restoration safety. Native response creation timestamps are not final timestamps.

| Main mode | Utility mode | Observed final answer | Mean | Native recall |
| --- | --- | --- | --- | --- |
| Off | Off | 26.99 / 32.88 s | 29.93 s | 8.88 / 20.40 s |
| On | Off | 23.81 / 23.92 s | 23.87 s | 6.84 / 6.99 s |
| Off | On | 19.11 / 21.89 s | 20.50 s | 4.79 / 5.22 s |
| On | On | 15.63 / 17.70 s | 16.66 s | 2.84 / 3.95 s |

All eight completed answers passed semantic review, all completion barriers
passed, and both corpus hashes and restored settings matched. Each Utility-on
cell avoided two of four real Utility calls (50%); all four filtering decisions
completed without fallback, adding 0.22–0.29 s each. Ordinary Utility still wrote
the four enabled-turn queries. The memory-only task used no Main action choices.

Observed final time includes client queue/network time, polling visibility delay
and filesystem persistence lag; it is not exact server completion time. Two
trials per cell and the variable baseline recall spans do not establish a general
speed guarantee or attribute every timing difference to the plugin. The measured
benefit is successful bounded filtering with fewer Utility generations; the
component and complete-answer timings have explicit, separate boundaries.
