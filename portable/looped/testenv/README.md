# Looped Mode isolated test project

Runs the plugin inside a real Agent Zero without touching anything else on the
machine, and without a real model.

## What it is

A compose project named `looped-test` with three containers on one private
network:

| Container | Role |
| --- | --- |
| `looped-test-a0` | A throwaway Agent Zero with the assembled plugin installed and its own empty data folder (`.run/usr`). |
| `looped-test-llm` | A scripted stub model (`stub_llm/server.py`). It replays each scenario's replies in order, so tests are deterministic. |
| `looped-test-driver` | Sends the chat messages and checks what the agent logged and what the stub model was asked. |

`scenarios.py` holds the scripted cases: passes agree, passes disagree and a
third decides, a malformed first pass, auto-mode checkpoints, merged final
answers, `/looped`, a second look after a tool error, mode off, and the two
experimental strategies.

## Guards

- **Nothing shared.** The network is internal: no internet, no published host
  ports. No GPU. The only host folder mounted read-write is `.run/` here.
- **No real model.** Every model slot points at the stub. Your model server is
  never contacted, so nothing can be unloaded or slowed.
- **Never pulls.** The Agent Zero image must already be local.
- **Scope lock.** Every Docker change goes through one function that always
  passes `-p looped-test`. The script never stops, restarts, removes or changes
  a container, network or volume outside that project.
- **Checks first.** Before starting it verifies the names and network are free
  or its own, that enough memory is free, and lists every other container it
  will leave alone. On a conflict it stops and reports; it does not rename or
  reuse anything.
- **Verifies afterwards.** It compares the other containers and GPU processes
  before and after the run, and confirms no `looped-test` container remains.
- **Capped.** About 9 GB of RAM and 6 CPU cores in total.

## Use

```powershell
.\run_tests.ps1 -WhatIf
```

Prints the checks and every action, and changes nothing.

```powershell
.\run_tests.ps1
```

Runs all scenarios, then removes the test project.

Other switches: `-Only 01_agree,02_tiebreak` (some scenarios), `-Keep` (leave
the containers up for inspection), `-Reuse` (reuse containers left by `-Keep`,
refreshing only the plugin files), `-Down` (remove the test project).

Results are written to `.run/results/results.json`.

## One-time setup: tokenizer cache

Agent Zero downloads a tokenizer file on first use, and the test network has no
internet. Copy it once from a container that has already run:

```powershell
.\run_tests.ps1 -SeedTokenizerFrom agent-zero-latest -WhatIf
```

Drop `-WhatIf` to do it. This is a read-only `docker cp` out of that container
into `seed/tiktoken-cache/` (not committed); the container is not changed.

## Tests against a real model

Not here. Anything that sends requests to a real model goes through
`../bench/run_bench.py --live`, which prints what it will touch and requires
the model name to be typed back before the first request.
