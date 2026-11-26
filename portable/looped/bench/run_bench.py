"""Benchmark Looped Mode strategies by driving the core directly.

    python run_bench.py --dry-run
        Simulated model. Checks the pipeline and prints the full table.
        The numbers are NOT evidence about any real model.

    python run_bench.py --live --endpoint http://127.0.0.1:8080/v1 --model NAME \
        --api-key-env LLAMA_API_KEY --suites arith,tool --tasks 100
        Real model, behind the warn-and-confirm gate in gate.py.

Arms: plain, reread, agree, deepen, stack (reread + agree). Every arm runs the
same tasks, so each is compared with ``plain`` task by task. A task is one
agent step, or in the ``multi`` suite several dependent steps against a mock
world (``multistep.py``), where every step goes through the arm's strategy.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
import multistep  # noqa: E402
import stats  # noqa: E402
import tasks as task_sets  # noqa: E402
from clients import OpenAIClient, SimulatedModel  # noqa: E402

ARMS: dict[str, dict[str, Any]] = {
    "plain": {"reread": False, "settings": None},
    "think": {"reread": False, "settings": None, "think": True},     # one call, reasoning on
    "reread": {"reread": True, "settings": None},
    "agree": {"reread": False, "settings": {"mode": "always"}},
    "deepen": {"reread": False,
               "settings": {"mode": "always", "strategies": {"deepen": {"enabled": True}}}},
    "stack": {"reread": True, "settings": {"mode": "always"}},
    # think when unsure: quick second pass, reasoning only when the two do not agree
    "escalate": {"reread": False,
                 "settings": {"mode": "always", "strategies": {"escalate": {"enabled": True}}}},
    # the same, with later passes shown the earlier ones instead of starting from scratch
    "carry": {"reread": False,
              "settings": {"mode": "always",
                           "strategies": {"escalate": {"enabled": True, "carry": True}}}},
}
REREAD_ON = merge_config({"strategies": {"reread": {"when": "always"}}})
# A multi-step task is one turn: lift the per-turn budget so every step is looked at.
MULTI_BUDGET = {"budget": {"max_extra_calls_per_turn": 64}}
STEPS_PER_MULTI_TASK = 7                            # for the request estimate only


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
    try:                                            # 5.00 and 5 are the same answer
        return float(given.replace(",", "")) == float(gold.replace(",", ""))
    except ValueError:
        pass
    if len(gold) == 1 and gold.isalpha():          # multiple choice letter
        return given[:1] == gold and (len(given) == 1 or not given[1].isalnum())
    return given.replace(",", "") == gold.replace(",", "")


def given(candidate) -> str:
    """What the chosen step said, shortened, for reading wrong answers afterwards."""
    if not candidate.valid:
        return "(invalid) " + str(candidate.raw)[:80]
    if candidate.kind == "final":
        return str(final_text(candidate.tool_args))[:80]
    return f"{candidate.tool_name} {json.dumps(candidate.tool_args, sort_keys=True)[:80]}"


class Replies:
    """Replies to the unchanged prompt, by kind and prompt key.

    The key is the task id, or for a step of a multi-step task the task id
    plus a digest of the prompt so far, so a reply is reused only by an arm
    that has taken the same steps up to that point.

    Kinds: ``plain`` (the first quick pass), ``second`` (the second quick pass,
    sampled with the first variant's settings) and ``think`` (reasoning on).
    An arm that sends the same prompt takes that pass from here instead of
    sampling again, so any difference between arms is the strategy's doing.
    With a ``path`` the replies are also appended to a file and read back by a
    later run, which then need not ask again.
    """

    def __init__(self, path: Path | None = None):
        self.path = path
        self.held: dict[tuple[str, str], tuple[str, str]] = {}
        self.tokens: dict[tuple[str, str], int] = {}
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    key = (row["kind"], row["id"])
                    self.held[key] = (row["raw"], row.get("reasoning", ""))
                    self.tokens[key] = int(row.get("tokens") or 0)

    def get(self, kind: str, task_id: str) -> tuple[str, str] | None:
        return self.held.get((kind, task_id))

    def put(self, kind: str, task_id: str, raw: str, reasoning: str, tokens: int = 0) -> None:
        self.held[(kind, task_id)] = (raw, reasoning)
        self.tokens[(kind, task_id)] = tokens
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"kind": kind, "id": task_id, "raw": raw,
                                         "reasoning": reasoning, "tokens": tokens}) + "\n")


async def resolve(prompt: list[dict[str, str]], key: str, arm: dict[str, Any], client,
                  shared: Replies | None, think_tokens: int | None, tools,
                  state: TurnState | None = None, iteration: int = 0):
    """One step in one arm: the chosen candidate, and what choosing it cost.

    ``key`` names the prompt in ``shared`` (see ``Replies``). ``tokens`` counts
    the completion tokens of the calls this arm made itself; ``used`` adds the
    replies it took from ``shared``, so it is what the step costs on its own.
    """
    store = None if arm["reread"] else shared       # a re-read prompt is a different prompt
    spent = getattr(client, "completion_tokens", 0)
    reused = 0

    async def unchanged(kind: str) -> tuple[str, str]:
        """The unchanged prompt, quick (``plain``) or with reasoning on (``think``)."""
        nonlocal reused
        held = store.get(kind, key) if store is not None else None
        if held is not None:
            used = store.tokens.get((kind, key), 0)
            if kind == "think" and think_tokens and used > think_tokens:
                # Kept under a larger limit. Under this one it would have been
                # cut off before the answer, with about this much reasoning.
                reused += think_tokens
                return "", held[1][:int(len(held[1]) * think_tokens / used)]
            reused += used
            return held
        options = {"thinking": True, "max_tokens": think_tokens} if kind == "think" else {}
        reply = await client.complete(prompt, **options)
        if store is not None:
            store.put(kind, key, reply[0], reply[1], getattr(client, "last_tokens", 0))
        return reply

    def cost(calls: int, outcome: str) -> dict[str, Any]:
        own = getattr(client, "completion_tokens", 0) - spent
        return {"calls": calls, "outcome": outcome, "tokens": own, "used": own + reused}

    kind = "think" if arm.get("think") else "plain"
    raw, reasoning = await unchanged(kind)
    if arm["settings"] is None:
        return check(build_candidate(raw, reasoning), tool_names=tools), cost(1, kind)
    cfg = merge_config(arm["settings"])

    async def sample(variant: int):
        nonlocal reused
        if variant != 1 or store is None:
            return await client.complete(prompt, **variant_params(cfg, variant))
        held = store.get("second", key)             # the second quick pass is shared too
        if held is None:
            held = await client.complete(prompt, **variant_params(cfg, variant))
            store.put("second", key, held[0], held[1], getattr(client, "last_tokens", 0))
        else:
            reused += store.tokens.get(("second", key), 0)
        return held

    async def ask(text: str, variant: int):
        return await client.complete(prompt + [{"role": "user", "content": text}],
                                     **variant_params(cfg, variant))

    async def think(note: str | None = None):
        if note is None:
            return await unchanged("think")
        return await client.complete(prompt + [{"role": "user", "content": note}],
                                     thinking=True, max_tokens=think_tokens)

    ctx = StepContext(cfg=cfg, state=state or TurnState(), sample=sample, ask=ask, think=think,
                      tool_names=tools)
    decision = await resolve_step(raw, reasoning, iteration, ctx)
    return decision.winner, cost(1 + decision.extra_calls, decision.outcome)


async def episode(task, arm: dict[str, Any], client,
                  shared: Replies | None = None,
                  think_tokens: int | None = None) -> dict[str, Any]:
    """One task in one arm. ``shared`` holds reusable replies (see ``Replies``)."""
    if task.kind == "multi":
        return await multi_episode(task, arm, client, shared, think_tokens)
    extra = reread.build(task.question, REREAD_ON) if arm["reread"] else None
    winner, cost = await resolve(task_sets.messages(task, extra), task.id, arm, client, shared,
                                 think_tokens, task_sets.TOOLS)
    return {"id": task.id, "correct": score(task, winner), "given": given(winner), **cost}


async def multi_episode(task: multistep.MultiTask, arm: dict[str, Any], client,
                        shared: Replies | None = None,
                        think_tokens: int | None = None) -> dict[str, Any]:
    """A task of several dependent steps: the world runs each step the arm chooses.

    The task passes when it ends with the right answer and the world is left as
    the task requires. ``resolved`` counts how each step was decided.
    """
    world, history, state = task.world(), task_sets.messages(task), TurnState()
    if arm["settings"] is not None:
        arm = {**arm, "settings": {**arm["settings"], **MULTI_BUDGET}}
    extra = reread.build(task.question, REREAD_ON) if arm["reread"] else None
    total = {"calls": 0, "tokens": 0, "used": 0}
    resolved: dict[str, int] = {}
    final, steps = None, 0
    while final is None and steps < task.max_steps:
        prompt = history + ([{"role": "user", "content": extra}] if extra else [])
        digest = hashlib.sha1(json.dumps(prompt).encode("utf-8")).hexdigest()[:16]
        winner, cost = await resolve(prompt, f"{task.id}#{digest}", arm, client, shared,
                                     think_tokens, task.tools, state, steps)
        steps += 1
        for name in total:
            total[name] += cost[name]
        resolved[cost["outcome"]] = resolved.get(cost["outcome"], 0) + 1
        history.append({"role": "assistant", "content": winner.raw.strip() or "(empty reply)"})
        if not winner.valid:
            history.append({"role": "user", "content": multistep.BAD_STEP})
        elif winner.kind == "final":
            final = winner
        else:
            history.append({"role": "user",
                            "content": world.run(winner.tool_name, winner.tool_args)})
    failed = task.failures(world)
    if final is None:
        failed.insert(0, "no_answer")
    elif not score(task, final):
        failed.insert(0, "answer")
    return {"id": task.id, "correct": not failed,
            "outcome": "failed: " + ",".join(failed) if failed else "passed",
            "given": given(final) if final is not None else "(no answer)",
            "form": task.form, "steps": steps, "resolved": resolved, **total}


class ServerDown(RuntimeError):
    """Several requests in a row failed: stop instead of waiting out every timeout."""


async def run_arm(name: str, items: list[task_sets.Task], client, concurrency: int,
                  on_row=None, max_errors: int = 3,
                  shared: Replies | None = None,
                  think_tokens: int | None = None) -> dict[str, Any]:
    gate_ = asyncio.Semaphore(max(1, concurrency))
    started = time.monotonic()
    done = streak = 0

    async def one(task):
        nonlocal done, streak
        async with gate_:
            if max_errors and streak >= max_errors:
                return None                         # the run is being abandoned
            try:
                row = await episode(task, ARMS[name], client, shared, think_tokens)
                streak = 0
            except Exception as error:
                row = {"id": task.id, "correct": False, "calls": 1,
                       "outcome": f"error: {type(error).__name__} {getattr(error, 'code', '')}".strip()}
                streak += 1
            if on_row:
                on_row(name, row)
            done += 1
            if done % 10 == 0 or done == len(items):
                print(f"  [{name}] {done}/{len(items)} tasks, {time.monotonic() - started:.0f}s",
                      file=sys.stderr, flush=True)
            return row
    rows = [row for row in await asyncio.gather(*(one(task) for task in items)) if row]
    if max_errors and streak >= max_errors:
        raise ServerDown(f"{streak} requests in a row failed in arm '{name}' "
                         f"after {len(rows)} tasks; stopping")
    return {"arm": name, "rows": rows, "seconds": time.monotonic() - started,
            "prompt_tokens": client.prompt_tokens, "completion_tokens": client.completion_tokens,
            "cut": getattr(client, "cut", 0)}


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
               "errors": sum(1 for r in result["rows"] if r["outcome"].startswith("error")),
               "cut": result.get("cut", 0),         # replies that ran into --max-tokens
               # a reply that is not a usable step: a format slip, not a wrong answer
               "malformed": sum(1 for r in result["rows"]
                                if str(r.get("given", "")).startswith("(invalid)"))}
        if baseline is not None and name != "plain":
            row.update(stats.paired(baseline, outcomes))
        table.append(row)
    return table


def markdown(table: list[dict[str, Any]], title: str) -> str:
    lines = [f"### {title}", "",
             "| Suite | Arm | n | Accuracy | 95% CI | Fixed | Broke | p vs plain | Malformed | "
             "Cut off | Calls/task | Time (s) |",
             "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in table:
        paired = "fixed" in row
        lines.append(
            f"| {row['suite']} | {row['arm']} | {row['n']} | {row['accuracy']:.1%} | "
            f"{row['ci_low']:.1%} to {row['ci_high']:.1%} | "
            f"{row['fixed'] if paired else '-'} | {row['broke'] if paired else '-'} | "
            f"{row['p']:.3f} | " if paired else
            f"| {row['suite']} | {row['arm']} | {row['n']} | {row['accuracy']:.1%} | "
            f"{row['ci_low']:.1%} to {row['ci_high']:.1%} | - | - | - | ")
        lines[-1] += (f"{row.get('malformed', 0)} | {row.get('cut', 0)} | "
                      f"{row['calls_per_task']:.2f} | {row['seconds']:.1f} |")
    return "\n".join(lines)


async def run(args, make_client, details: dict[str, Any] | None = None,
              checkpoint=None) -> list[dict[str, Any]]:
    """Run every arm on every suite. Per-task rows go into ``details`` when given.

    ``checkpoint(suite, arm, row)`` is called as each task finishes, so a run
    that dies keeps what it measured.
    """
    table = []
    replies = getattr(args, "replies", None)
    shared = Replies(replies) if replies or getattr(args, "share_first_pass", False) else None
    for suite in args.suites:
        items = (task_sets.from_jsonl(Path(suite)) if suite.endswith(".jsonl")
                 else task_sets.generated(suite, args.tasks, args.seed, args.split))
        if args.tasks and len(items) > args.tasks:
            items = items[:args.tasks]
        results = {}
        stem = Path(suite).stem
        for name in args.arms:
            results[name] = await run_arm(
                name, items, make_client(items), args.concurrency,
                on_row=(lambda arm, row, stem=stem: checkpoint(stem, arm, row)) if checkpoint else None,
                max_errors=getattr(args, "max_errors", 3), shared=shared,
                think_tokens=getattr(args, "think_max_tokens", None))
        table.extend(summarise(Path(suite).stem, results))
        if details is not None:
            details[Path(suite).stem] = {name: result["rows"] for name, result in results.items()}
    return table


def parse(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="simulated model; pipeline check only")
    mode.add_argument("--live", action="store_true", help="real model, behind the confirm gate")
    parser.add_argument("--suites", default="arith,tool",
                        help="comma list of generated suites (arith, tool, arith_hard, tool_hard, arith_chain, multi) "
                             "or .jsonl paths")
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
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds per request")
    parser.add_argument("--pause", type=float, default=0.0,
                        help="idle seconds after each request, to go easy on a shared server")
    parser.add_argument("--max-errors", type=int, default=3,
                        help="stop after this many failed requests in a row (0 = never)")
    parser.add_argument("--share-first-pass", action="store_true",
                        help="agree and deepen take their first pass from the plain arm's reply "
                             "instead of sampling again (run plain first); calls still count it")
    parser.add_argument("--replies", type=Path, default=None,
                        help="file that keeps the replies to the unchanged prompt (quick and "
                             "reasoning); a later run with the same file reuses them instead "
                             "of asking again. Implies --share-first-pass")
    parser.add_argument("--think-max-tokens", type=int, default=10000,
                        help="token limit for calls that reason first; a kept reasoning "
                             "reply longer than this counts as cut off")
    parser.add_argument("--thinking", choices=("default", "on", "off"), default="default",
                        help="ask the chat template to reason first or not (llama.cpp "
                             "chat_template_kwargs.enable_thinking); default leaves the server's setting")
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
        per_task = {"plain": 1, "think": 1, "reread": 1, "agree": 2.3, "deepen": 2, "stack": 2.3,
                    "escalate": 2.4, "carry": 2.5}
        steps = sum(STEPS_PER_MULTI_TASK if suite in multistep.SUITES else 1 for suite in args.suites)
        estimate = int(sum(per_task[name] for name in args.arms) * args.tasks * steps)
        if not gate.confirm_live(args.endpoint, args.model, estimate, args.concurrency,
                                 api_key=key, allow_model_swap=args.allow_model_swap,
                                 allow_unknown_state=args.allow_unknown_state,
                                 assume_yes=args.yes):
            return 2
        # --split picks among generated tasks only; a run of .jsonl files has none.
        split = (f"{args.split} split, seed {args.seed}"
                 if any(not suite.endswith(".jsonl") for suite in args.suites) else "question files")
        title = f"{args.label or args.model} ({split}, thinking {args.thinking})"

        extra = ({} if args.thinking == "default" else
                 {"chat_template_kwargs": {"enable_thinking": args.thinking == "on"}})

        def make_client(items):
            return OpenAIClient(args.endpoint, args.model, key, max_tokens=args.max_tokens,
                                extra=extra, timeout=args.timeout,
                                pause=args.pause)

    args.out.mkdir(parents=True, exist_ok=True)
    stem = ("dry-run" if args.dry_run else (args.label or args.model).replace("/", "_")) \
        + f"-{args.split}-{time.strftime('%Y%m%d-%H%M%S')}"
    partial = args.out / f"{stem}.rows.jsonl"

    def checkpoint(suite: str, arm: str, row: dict[str, Any]) -> None:
        with partial.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"suite": suite, "arm": arm, **row}) + "\n")

    details: dict[str, Any] = {}
    try:
        table = asyncio.run(run(args, make_client, details, checkpoint))
    except ServerDown as error:
        print(f"\nSTOPPED: {error}.\nRows measured so far are in {partial}", file=sys.stderr)
        return 3
    report = markdown(table, title)
    print(report)
    (args.out / f"{stem}.json").write_text(json.dumps(
        {"title": title, "args": {k: str(v) for k, v in vars(args).items()}, "table": table,
         "rows": details},
        indent=2), encoding="utf-8")
    (args.out / f"{stem}.md").write_text(report + "\n", encoding="utf-8")
    print(f"\nSaved: {args.out / (stem + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
