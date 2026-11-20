"""Benchmark Looped Mode strategies by driving the core directly.

    python run_bench.py --dry-run
        Simulated model. Checks the pipeline and prints the full table.
        The numbers are NOT evidence about any real model.

    python run_bench.py --live --endpoint http://127.0.0.1:8080/v1 --model NAME \
        --api-key-env LLAMA_API_KEY --suites arith,tool --tasks 100
        Real model, behind the warn-and-confirm gate in gate.py.

Arms: plain, reread, agree, deepen, stack (reread + agree). Every arm runs the
same tasks, so each is compared with ``plain`` task by task.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from core import StepContext, TurnState, build_candidate, canonical_key, merge_config, resolve_step  # noqa: E402
from core.canonical import final_text, normalise_answer  # noqa: E402
from core.sampling import variant_params  # noqa: E402
from core.strategies import reread  # noqa: E402
from core.verify import check  # noqa: E402

import gate  # noqa: E402
import stats  # noqa: E402
import tasks as task_sets  # noqa: E402
from clients import OpenAIClient, SimulatedModel  # noqa: E402

ARMS: dict[str, dict[str, Any]] = {
    "plain": {"reread": False, "settings": None},
    "reread": {"reread": True, "settings": None},
    "agree": {"reread": False, "settings": {"mode": "always"}},
    "deepen": {"reread": False,
               "settings": {"mode": "always", "strategies": {"deepen": {"enabled": True}}}},
    "stack": {"reread": True, "settings": {"mode": "always"}},
}
REREAD_ON = merge_config({"strategies": {"reread": {"when": "always"}}})


def score(task: task_sets.Task, candidate) -> bool:
    if not candidate.valid:
        return False
    if task.kind == "tool":
        return candidate.key == canonical_key(task.tool_name, task.tool_args)
    if candidate.kind != "final":
        return False
    given, gold = normalise_answer(final_text(candidate.tool_args)), normalise_answer(task.answer)
    if given == gold:
        return True
    if len(gold) == 1 and gold.isalpha():          # multiple choice letter
        return given[:1] == gold and (len(given) == 1 or not given[1].isalnum())
    return given.replace(",", "") == gold.replace(",", "")


async def episode(task: task_sets.Task, arm: dict[str, Any], client) -> dict[str, Any]:
    extra = reread.build(task.question, REREAD_ON) if arm["reread"] else None
    prompt = task_sets.messages(task, extra)
    raw, reasoning = await client.complete(prompt)
    if arm["settings"] is None:
        winner = check(build_candidate(raw, reasoning), tool_names=task_sets.TOOLS)
        return {"id": task.id, "correct": score(task, winner), "calls": 1, "outcome": "plain"}
    cfg = merge_config(arm["settings"])

    async def sample(variant: int):
        return await client.complete(prompt, **variant_params(cfg, variant))

    async def ask(text: str, variant: int):
        return await client.complete(prompt + [{"role": "user", "content": text}],
                                     **variant_params(cfg, variant))

    ctx = StepContext(cfg=cfg, state=TurnState(), sample=sample, ask=ask,
                      tool_names=task_sets.TOOLS)
    decision = await resolve_step(raw, reasoning, 0, ctx)
    return {"id": task.id, "correct": score(task, decision.winner),
            "calls": 1 + decision.extra_calls, "outcome": decision.outcome}


async def run_arm(name: str, items: list[task_sets.Task], client, concurrency: int) -> dict[str, Any]:
    gate_ = asyncio.Semaphore(max(1, concurrency))
    started = time.monotonic()

    async def one(task):
        async with gate_:
            try:
                return await episode(task, ARMS[name], client)
            except Exception as error:
                return {"id": task.id, "correct": False, "calls": 1,
                        "outcome": f"error: {type(error).__name__}"}
    rows = await asyncio.gather(*(one(task) for task in items))
    return {"arm": name, "rows": rows, "seconds": time.monotonic() - started,
            "prompt_tokens": client.prompt_tokens, "completion_tokens": client.completion_tokens}


def summarise(suite: str, results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = [row["correct"] for row in results["plain"]["rows"]] if "plain" in results else None
    table = []
    for name, result in results.items():
        outcomes = [row["correct"] for row in result["rows"]]
        low, high = stats.bootstrap_ci(outcomes)
        row = {"suite": suite, "arm": name, "n": len(outcomes),
               "accuracy": sum(outcomes) / len(outcomes) if outcomes else 0.0,
               "ci_low": low, "ci_high": high,
               "calls_per_task": sum(r["calls"] for r in result["rows"]) / max(1, len(outcomes)),
               "seconds": result["seconds"], "prompt_tokens": result["prompt_tokens"],
               "completion_tokens": result["completion_tokens"],
               "errors": sum(1 for r in result["rows"] if r["outcome"].startswith("error"))}
        if baseline is not None and name != "plain":
            row.update(stats.paired(baseline, outcomes))
        table.append(row)
    return table


def markdown(table: list[dict[str, Any]], title: str) -> str:
    lines = [f"### {title}", "",
             "| Suite | Arm | n | Accuracy | 95% CI | Fixed | Broke | p vs plain | Calls/task | Time (s) |",
             "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in table:
        paired = "fixed" in row
        lines.append(
            f"| {row['suite']} | {row['arm']} | {row['n']} | {row['accuracy']:.1%} | "
            f"{row['ci_low']:.1%} to {row['ci_high']:.1%} | "
            f"{row['fixed'] if paired else '-'} | {row['broke'] if paired else '-'} | "
            f"{row['p']:.3f} | " if paired else
            f"| {row['suite']} | {row['arm']} | {row['n']} | {row['accuracy']:.1%} | "
            f"{row['ci_low']:.1%} to {row['ci_high']:.1%} | - | - | - | ")
        lines[-1] += f"{row['calls_per_task']:.2f} | {row['seconds']:.1f} |"
    return "\n".join(lines)


async def run(args, make_client) -> list[dict[str, Any]]:
    table = []
    for suite in args.suites:
        items = (task_sets.from_jsonl(Path(suite)) if suite.endswith(".jsonl")
                 else task_sets.generated(suite, args.tasks, args.seed, args.split))
        if args.tasks and len(items) > args.tasks:
            items = items[:args.tasks]
        results = {}
        for name in args.arms:
            results[name] = await run_arm(name, items, make_client(items), args.concurrency)
        table.extend(summarise(Path(suite).stem, results))
    return table


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="simulated model; pipeline check only")
    mode.add_argument("--live", action="store_true", help="real model, behind the confirm gate")
    parser.add_argument("--suites", default="arith,tool",
                        help="comma list of generated suites (arith, tool) or .jsonl paths")
    parser.add_argument("--arms", default="plain,reread,agree,deepen,stack")
    parser.add_argument("--tasks", type=int, default=100)
    parser.add_argument("--split", choices=("dev", "heldout"), default="dev")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--api-key-env", default="", help="environment variable holding the API key")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--allow-model-swap", action="store_true")
    parser.add_argument("--allow-unknown-state", action="store_true")
    parser.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    parser.add_argument("--out", type=Path, default=HERE / "results")
    args = parser.parse_args(argv)
    args.suites = [item for item in args.suites.split(",") if item]
    args.arms = [item for item in args.arms.split(",") if item]
    unknown = [name for name in args.arms if name not in ARMS]
    if unknown:
        parser.error(f"unknown arms: {unknown}")
    if args.live and not (args.endpoint and args.model):
        parser.error("--live needs --endpoint and --model")
    return args


def main(argv=None) -> int:
    args = parse(argv)
    if args.dry_run:
        title = "SIMULATED model - pipeline check only, not evidence about any real model"

        def make_client(items):
            return SimulatedModel({task.question: task for task in items}, seed=args.seed)
    else:
        key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
        per_task = {"plain": 1, "reread": 1, "agree": 2.3, "deepen": 2, "stack": 2.3}
        estimate = int(sum(per_task[name] for name in args.arms) * args.tasks * len(args.suites))
        if not gate.confirm_live(args.endpoint, args.model, estimate, args.concurrency,
                                 api_key=key, allow_model_swap=args.allow_model_swap,
                                 allow_unknown_state=args.allow_unknown_state,
                                 assume_yes=args.yes):
            return 2
        title = f"{args.label or args.model} ({args.split} split, seed {args.seed})"

        def make_client(items):
            return OpenAIClient(args.endpoint, args.model, key, max_tokens=args.max_tokens)

    table = asyncio.run(run(args, make_client))
    report = markdown(table, title)
    print(report)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = ("dry-run" if args.dry_run else (args.label or args.model).replace("/", "_")) \
        + f"-{args.split}-{time.strftime('%Y%m%d-%H%M%S')}"
    (args.out / f"{stem}.json").write_text(json.dumps(
        {"title": title, "args": {k: str(v) for k, v in vars(args).items()}, "table": table},
        indent=2), encoding="utf-8")
    (args.out / f"{stem}.md").write_text(report + "\n", encoding="utf-8")
    print(f"\nSaved: {args.out / (stem + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
