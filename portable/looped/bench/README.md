# Looped Mode benchmark

Measures whether the strategies help a given model, by driving the same `core`
code the plugin uses directly against an OpenAI-compatible endpoint. One agent
step per task; every arm runs the same tasks and is compared with `plain` task
by task.

## Arms

| Arm | What runs |
| --- | --- |
| `plain` | One call. |
| `reread` | One call, task repeated in the prompt. |
| `agree` | Agreement between passes, tie-break, merged long answers. |
| `deepen` | Reason twice (experimental). |
| `stack` | `reread` + `agree`. |

## Tasks

- `arith`: generated multi-step arithmetic, answered through the `response` tool.
- `tool`: generated requests that map to one mock tool with exact arguments.
- Any `.jsonl` file (format in `tasks.py`), for real datasets such as MMLU-Pro,
  GSM8K or ARC-Challenge subsets. None are bundled or downloaded.

Generated sets have `dev` and `heldout` splits that never overlap. Tune settings
on `dev`; report `heldout`. Trying many settings and reporting the best one on
the same questions finds luck, not improvement.

## Output

Accuracy with a 95% bootstrap interval, tasks fixed and broken relative to
`plain`, an exact McNemar p-value, model calls per task, and wall time. Saved as
JSON and Markdown under `results/` (not committed).

## Dry run

```powershell
python run_bench.py --dry-run
```

Uses a simulated model to check the pipeline end to end. **Its numbers are not
evidence about any real model.** The simulator's errors are independent between
calls, which is the best case for agreement; real models repeat their mistakes.

## Real model

```powershell
python run_bench.py --live --endpoint http://127.0.0.1:8080/v1 --model MODEL_NAME --api-key-env LLAMA_API_KEY --split dev --tasks 100
```

Before the first request the gate (`gate.py`):

- prints the endpoint, model, request count and concurrency;
- checks, read-only, whether that model is the one already loaded;
- **refuses** if the request would make the server load a different model
  (override: `--allow-model-swap`), or if it cannot tell (override:
  `--allow-unknown-state`);
- explains the effect on running sessions: requests queue with them, and a
  single-slot server's prompt cache is overwritten;
- requires the model name to be typed back (`--yes` skips only this step).

The API key is read from the environment variable you name; it is never written
to results.

## Comparison plan

1. Loaded 27B model: all arms, `dev` then `heldout`. Answers "does the plugin
   help the model I run".
2. SenseNova-Loop-9B: `plain` (and `stack`, to see whether they add up).
   Needs a llama.cpp build with SenseNova Loop support and a free model slot.
3. A similar-size ordinary model (about 9B): all arms. This is the size-matched
   test of "plugin versus a built-in loop".

A thinking-on control is not built in: run the same command against a preset
with reasoning enabled and compare.
