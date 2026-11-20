"""Benchmark tasks: generated sets for a quick check, JSONL for real datasets.

Every task is one agent step: a system prompt in the host's JSON step format,
a user task, and a gold outcome. A task is ``qa`` (the answer goes in the
``response`` tool, scored by matching the gold answer) or ``tool`` (scored by
the canonical key of the gold tool call).

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


def generated(suite: str, count: int, seed: int = 7, split: str = "heldout") -> list[Task]:
    """``count`` tasks of one split. ``dev`` and ``heldout`` never overlap."""
    maker = {"arith": _arith, "tool": _tool}[suite]
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
            question += "\nAnswer with the letter only."
        tasks.append(Task(id=str(row.get("id", f"{path.stem}-{number}")),
                          kind=row.get("kind", "qa"), question=question,
                          answer=str(row.get("answer", "")),
                          tool_name=row.get("tool_name", ""),
                          tool_args=row.get("tool_args") or {},
                          suite=suite or path.stem))
    return tasks


def messages(task: Task, extra: str | None = None) -> list[dict[str, str]]:
    prompt = [{"role": "system", "content": SYSTEM},
              {"role": "user", "content": task.question}]
    if extra:
        prompt.append({"role": "user", "content": extra})
    return prompt
