"""Benchmark tasks: generated sets for a quick check, JSONL for real datasets.

Every task here is one agent step: a system prompt in the host's JSON step
format, a user task, and a gold outcome. A task is ``qa`` (the answer goes in
the ``response`` tool, scored by matching the gold answer) or ``tool`` (scored
by the canonical key of the gold tool call). Tasks of several dependent steps
(the ``multi`` suite) are in ``multistep.py``.

Generated sets are deterministic for a seed and split into ``dev`` and
``heldout`` halves: tune settings on ``dev`` only and report ``heldout``.

JSONL format, one object per line:
  {"id": "...", "kind": "qa", "question": "...", "answer": "42"}
  {"id": "...", "kind": "qa", "question": "...", "choices": ["..."], "answer": "B"}
  {"id": "...", "kind": "tool", "question": "...", "tool_name": "...", "tool_args": {...}}
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import multistep

TOOLS = {
    "write_file": "Write text to a file. args: path, text",
    "read_file": "Read a file. args: path",
    "delete_file": "Delete a file. args: path",
    "search_web": "Search the web. args: query",
    "run_shell": "Run a shell command. args: command",
    "send_message": "Send a message to a person. args: to, text",
    "response": "Give the final answer to the user. args: text",
}

SYSTEM = (
    "You are an agent that acts by replying with exactly one JSON object and "
    "nothing else:\n"
    '{"thoughts": ["..."], "headline": "...", "tool_name": "...", "tool_args": {...}}\n\n'
    "Tools:\n" + "\n".join(f"- {name}: {text}" for name, text in TOOLS.items()) + "\n\n"
    "To answer a question, use the response tool and put only the final answer "
    "in text. To act, use the single tool that does what was asked, with exact "
    "argument values from the request."
)


@dataclass
class Task:
    id: str
    kind: str                      # qa | tool
    question: str
    answer: str = ""
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    suite: str = ""


def _arith(rng: random.Random, index: int) -> Task:
    a, b, c, d = (rng.randint(12, 97) for _ in range(4))
    form = (index // 2) % 4         # pairs share a form, so both splits get every form
    if form == 0:
        question = (f"A shop has {a} boxes with {b} items each. It sells {c} items and then "
                    f"receives {d} more. How many items does it have now?")
        answer = a * b - c + d
    elif form == 1:
        question = (f"Start with {a}. Multiply by {b}, subtract {c}, then subtract {d} again. "
                    f"What is the result?")
        answer = a * b - c - d
    elif form == 2:
        question = (f"Three trucks carry {a}, {b} and {c} crates. Each crate holds {d % 9 + 2} "
                    f"parts. How many parts in total?")
        answer = (a + b + c) * (d % 9 + 2)
    else:
        question = (f"A tank holds {a * b} litres. {c} litres leak out each hour for "
                    f"{d % 7 + 2} hours. How many litres remain?")
        answer = a * b - c * (d % 7 + 2)
    return Task(id=f"arith-{index:04d}", kind="qa", question=question + " Answer with the number only.",
                answer=str(answer), suite="arith")


def _tool(rng: random.Random, index: int) -> Task:
    names = ["report", "notes", "todo", "summary", "draft", "log", "config", "data"]
    people = ["Ana", "Ben", "Chen", "Dita", "Eli", "Fay"]
    stem, ext = rng.choice(names), rng.choice(["txt", "md", "csv"])
    path = f"{stem}_{rng.randint(1, 99)}.{ext}"
    form = (index // 2) % 6         # pairs share a form, so both splits get every form
    if form == 0:
        text = f"version {rng.randint(1, 9)}.{rng.randint(0, 9)}"
        return Task(f"tool-{index:04d}", "tool", f"Save the text '{text}' in the file {path}.",
                    tool_name="write_file", tool_args={"path": path, "text": text}, suite="tool")
    if form == 1:
        return Task(f"tool-{index:04d}", "tool", f"Show me what is in {path}.",
                    tool_name="read_file", tool_args={"path": path}, suite="tool")
    if form == 2:
        return Task(f"tool-{index:04d}", "tool", f"Get rid of the file {path}; I no longer need it.",
                    tool_name="delete_file", tool_args={"path": path}, suite="tool")
    if form == 3:
        query = f"{stem} format specification {rng.randint(2019, 2026)}"
        return Task(f"tool-{index:04d}", "tool", f"Look up '{query}' online.",
                    tool_name="search_web", tool_args={"query": query}, suite="tool")
    if form == 4:
        command = f"wc -l {path}"
        return Task(f"tool-{index:04d}", "tool", f"Run the command `{command}`.",
                    tool_name="run_shell", tool_args={"command": command}, suite="tool")
    person, text = rng.choice(people), f"the {stem} is ready"
    return Task(f"tool-{index:04d}", "tool", f"Tell {person} that {text}. Use exactly: '{text}'.",
                tool_name="send_message", tool_args={"to": person, "text": text}, suite="tool")


def _arith_hard(rng: random.Random, index: int) -> Task:
    """Four or five operations with larger intermediate values."""
    a, b, c, d, e, f = (rng.randint(13, 97) for _ in range(6))
    k = rng.randint(3, 9)
    form = (index // 2) % 4
    if form == 0:
        question = (f"A depot has {a} pallets of {b} boxes. {c} boxes are removed. Every remaining box "
                    f"holds {k} units, and {d} loose units are added. How many units are there?")
        answer = (a * b - c) * k + d
    elif form == 1:
        question = (f"One order is {a} cases of {b} bottles, a second is {c} cases of {d} bottles, and "
                    f"{e} cases of {f} bottles are sent back. How many bottles were kept?")
        answer = a * b + c * d - e * f
    elif form == 2:
        question = (f"{a} crates of {b} parts and {c} crates of {d} parts are pooled, {e} parts are "
                    f"scrapped, and the rest are packed into kits of {k}. How many parts are left over "
                    f"after packing as many full kits as possible?")
        answer = (a * b + c * d - e) % k
    else:
        question = (f"A farm has {a} rows of {b} trees with {k} baskets of fruit per tree. It sells "
                    f"{c} lots of {d} baskets. How many baskets remain?")
        answer = a * b * k - c * d
    return Task(id=f"arith_hard-{index:04d}", kind="qa",
                question=question + " Answer with the number only.", answer=str(answer),
                suite="arith_hard")


def _arith_chain(rng: random.Random, index: int) -> Task:
    """A long running calculation: seven or eight dependent steps, one slip spoils it."""
    a, b, c, d, e, f, g, h = (rng.randint(13, 97) for _ in range(8))
    big, m, k = rng.randint(113, 487), rng.choice([101, 103, 107, 109, 113, 127]), rng.randint(3, 9)
    form = (index // 2) % 2
    if form == 0:
        value = ((a * big + c * d - e) % m) * f - g * h + k
        steps = (f"Start with {a}. Multiply by {big}. Add the product of {c} and {d}. Subtract {e}. "
                 f"Replace the value by its remainder on division by {m}. Multiply by {f}. "
                 f"Subtract the product of {g} and {h}. Add {k}.")
    else:
        value = (((big * b - c) * k + d * e) % m + f) * g - h     # stays positive before the remainder
        steps = (f"Start with {big}. Multiply by {b}. Subtract {c}. Multiply by {k}. "
                 f"Add the product of {d} and {e}. Replace the value by its remainder on division "
                 f"by {m}. Add {f}. Multiply by {g}. Subtract {h}.")
    return Task(id=f"arith_chain-{index:04d}", kind="qa",
                question=steps + " What is the final value? Put just that number in the answer text.",
                answer=str(value), suite="arith_chain")


def _tool_hard(rng: random.Random, index: int) -> Task:
    """One correct tool call, with a distractor file, person or action in the request."""
    names = ["report", "notes", "todo", "summary", "draft", "log", "config", "data"]
    people = ["Ana", "Ben", "Chen", "Dita", "Eli", "Fay"]
    first, second = rng.sample(names, 2)
    one = f"{first}_{rng.randint(1, 99)}.{rng.choice(['txt', 'md', 'csv'])}"
    two = f"{second}_{rng.randint(1, 99)}.{rng.choice(['txt', 'md', 'csv'])}"
    ident = f"tool_hard-{index:04d}"
    form = (index // 2) % 6
    if form == 0:
        text = f"build {rng.randint(100, 999)}"
        return Task(ident, "tool", f"Do not delete {one}. Save the text '{text}' in {two} instead.",
                    tool_name="write_file", tool_args={"path": two, "text": text}, suite="tool_hard")
    if form == 1:
        return Task(ident, "tool", f"Once I have seen what is in {one} I will want {two} removed. "
                                   f"Do only the first of those now.",
                    tool_name="read_file", tool_args={"path": one}, suite="tool_hard")
    if form == 2:
        return Task(ident, "tool", f"I no longer need {one}, but {two} must stay. Remove the one I do not need.",
                    tool_name="delete_file", tool_args={"path": one}, suite="tool_hard")
    if form == 3:
        query = f"{first} file format {rng.randint(2019, 2026)}"
        return Task(ident, "tool", f"Without opening {one}, look up '{query}' online.",
                    tool_name="search_web", tool_args={"query": query}, suite="tool_hard")
    if form == 4:
        command = f"wc -l {one}"
        return Task(ident, "tool", f"Run `{command}`. Careful: that file, not {two}.",
                    tool_name="run_shell", tool_args={"command": command}, suite="tool_hard")
    writer, reader = rng.sample(people, 2)
    text = f"the {first} is ready"
    return Task(ident, "tool", f"{writer} wrote {one}. Tell {reader}, not {writer}, that {text}. "
                               f"Use exactly: '{text}'.",
                tool_name="send_message", tool_args={"to": reader, "text": text}, suite="tool_hard")


def generated(suite: str, count: int, seed: int = 7, split: str = "heldout") -> list[Task]:
    """``count`` tasks of one split. ``dev`` and ``heldout`` never overlap."""
    maker = {"arith": _arith, "tool": _tool, "arith_hard": _arith_hard, "tool_hard": _tool_hard,
             "arith_chain": _arith_chain, "multi": multistep.make}[suite]
    rng = random.Random(f"{suite}-{seed}")
    tasks = [maker(rng, index) for index in range(count * 2)]
    return tasks[0::2] if split == "dev" else tasks[1::2]


def from_jsonl(path: Path, suite: str | None = None) -> list[Task]:
    tasks = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        row = json.loads(line)
        question = str(row["question"])
        choices = row.get("choices")
        if isinstance(choices, list) and choices:
            letters = "ABCDEFGHIJ"
            question += "\n" + "\n".join(f"{letters[i]}. {choice}" for i, choice in enumerate(choices))
            question += "\nPut just the letter of the correct choice in the answer text."
        tasks.append(Task(id=str(row.get("id", f"{path.stem}-{number}")),
                          kind=row.get("kind", "qa"), question=question,
                          answer=str(row.get("answer", "")),
                          tool_name=row.get("tool_name", ""),
                          tool_args=row.get("tool_args") or {},
                          suite=suite or path.stem))
    return tasks


def messages(task, extra: str | None = None) -> list[dict[str, str]]:
    prompt = [{"role": "system", "content": getattr(task, "system", SYSTEM)},
              {"role": "user", "content": task.question}]
    if extra:
        prompt.append({"role": "user", "content": extra})
    return prompt
