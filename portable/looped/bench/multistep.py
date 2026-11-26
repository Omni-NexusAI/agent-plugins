"""Multi-step benchmark tasks: several dependent steps against a mock world.

Each task is a handful of text files, an outbox, and a request that takes five
to seven tool calls, where a later step depends on what an earlier one
returned. The world runs each step the agent chooses and returns the result;
the task ends with the ``response`` tool or at the step limit. A task passes
only when the final answer, the files left behind and the messages sent are all
right, so one bad step spoils it and a strategy has to be right at every step.

Forms (``multi`` suite):
  trail    follow a chain of files, choosing each next file from a running total
  ledger   apply stock changes, work out a total, write it, send it, report it
  cleanup  delete the files one list marks, except those another list protects
  routing  assign two tickets by category and priority, message both owners
  recount  reconcile two counts with a recount, write the total
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

TOOLS = {
    "read_file": "Read a file. args: path",
    "write_file": "Write text to a file, replacing what it held. args: path, text",
    "delete_file": "Delete a file. args: path",
    "send_message": "Send a message to a person. args: to, text",
    "response": "Give the final answer to the user and end the task. args: text",
}

SYSTEM = (
    "You are an agent that acts by replying with exactly one JSON object and "
    "nothing else:\n"
    '{"thoughts": ["..."], "headline": "...", "tool_name": "...", "tool_args": {...}}\n\n'
    "Tools:\n" + "\n".join(f"- {name}: {text}" for name, text in TOOLS.items()) + "\n\n"
    "Take one step per reply. After each step you are given the tool's result. "
    "Use exact file names and values from the task and from tool results, and "
    "change nothing the task did not ask you to change. When the task is "
    "finished, use the response tool and put only the final answer in text."
)

BAD_STEP = ("That reply was not a usable step. Reply with exactly one JSON object in "
            "the format you were given, using one of the listed tools.")

SUITES = ("multi",)
FORMS = ("trail", "ledger", "cleanup", "routing", "recount")
STEMS = ["report", "notes", "todo", "summary", "draft", "log", "config", "data", "index", "audit"]
PEOPLE = ["Ana", "Ben", "Chen", "Dita", "Eli", "Fay", "Gus", "Hana"]
GOODS = ["bolts", "nuts", "gears", "springs", "washers", "valves", "clamps", "hinges"]
_COMMA = re.compile(r"\s*,\s*")


def _tidy(text: Any) -> str:
    """A written value without cosmetic differences: case, spacing, wrapping marks."""
    return _COMMA.sub(",", " ".join(str(text).split())).strip("*_`\"' .!").lower()


def same(given: Any, gold: Any) -> bool:
    one, two = _tidy(given), _tidy(gold)
    if one == two:
        return True
    try:
        return float(one.replace(",", "")) == float(two.replace(",", ""))
    except ValueError:
        return False


class World:
    """The files and outbox a task acts on. ``run`` executes one tool call."""

    def __init__(self, files: dict[str, str]):
        self.files = dict(files)
        self.sent: list[tuple[str, str]] = []

    def run(self, tool: str, args: dict[str, Any]) -> str:
        name = str(tool).strip().lower()
        path = str(args.get("path", "")).strip()
        path = path[2:] if path.startswith("./") else path
        if name in ("read_file", "write_file", "delete_file") and not path:
            return f"Error: {name} needs a path."
        if name == "read_file":
            return self.files[path] if path in self.files else f"Error: no such file: {path}"
        if name == "write_file":
            if "text" not in args:
                return "Error: write_file needs text."
            self.files[path] = str(args["text"])
            return f"Wrote {path}."
        if name == "delete_file":
            if path not in self.files:
                return f"Error: no such file: {path}"
            del self.files[path]
            return f"Deleted {path}."
        if name == "send_message":
            to = str(args.get("to", "")).strip()
            if not to or "text" not in args:
                return "Error: send_message needs to and text."
            self.sent.append((to, str(args["text"])))
            return f"Message sent to {to}."
        return f"Error: unknown tool: {tool}"


@dataclass
class MultiTask:
    id: str
    question: str
    files: dict[str, str]
    answer: str
    final_files: dict[str, str]                     # every file that must exist at the end
    sent: list[tuple[str, str]] = field(default_factory=list)   # required messages, any order
    script: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # one correct solution
    form: str = ""
    suite: str = "multi"
    kind: str = "multi"
    system: str = SYSTEM
    tools = TOOLS

    @property
    def max_steps(self) -> int:
        return len(self.script) + 4

    def world(self) -> World:
        return World(self.files)

    def failures(self, world: World) -> list[str]:
        """What the world got wrong, apart from the final answer."""
        failed = []
        if set(world.files) != set(self.final_files) or any(
                not same(world.files[path], text) for path, text in self.final_files.items()):
            failed.append("files")
        if sorted((to.lower(), _tidy(text)) for to, text in world.sent) != sorted(
                (to.lower(), _tidy(text)) for to, text in self.sent):
            failed.append("messages")
        return failed


class _Names:
    """File names that do not repeat within a task."""

    def __init__(self, rng: random.Random):
        self.rng, self.used = rng, set()

    def file(self, stem: str | None = None) -> str:
        while True:
            name = (f"{stem or self.rng.choice(STEMS)}_{self.rng.randint(1, 99)}."
                    f"{self.rng.choice(['txt', 'md', 'csv'])}")
            if name not in self.used:
                self.used.add(name)
                return name


def _code(rng: random.Random) -> str:
    return "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(2)) + f"-{rng.randint(1000, 9999)}"


def _trail(rng: random.Random, ident: str) -> MultiTask:
    names, length = _Names(rng), 5
    chain = [names.file() for _ in range(length)]
    last, decoys = names.file(), [names.file() for _ in range(length)]
    codes: list[str] = []
    while len(codes) < length + 1:
        fresh = _code(rng)
        if fresh not in codes:
            codes.append(fresh)
    code, *wrong = codes
    files = {last: f"code: {code}"}
    files.update({decoy: f"code: {text}" for decoy, text in zip(decoys, wrong)})
    total = 0
    for index, name in enumerate(chain):
        value = rng.randint(113, 987)
        total += value
        onward = chain[index + 1] if index + 1 < length else last
        odd, even = (onward, decoys[index]) if total % 2 else (decoys[index], onward)
        files[name] = f"value: {value}\nodd: {odd}\neven: {even}"
    question = (
        f"Start by reading {chain[0]}. Each file on the trail holds a value and two file "
        "names. Keep a running total of the values of every trail file you have read so "
        "far, including the current one. When the running total is odd, read the file "
        "on the 'odd:' line next; when it is even, read the file on the 'even:' line. "
        "Go on until you read a file with a 'code:' line, then reply with just that code.")
    script = [("read_file", {"path": name}) for name in chain + [last]]
    script.append(("response", {"text": code}))
    return MultiTask(ident, question, files, code, dict(files), [], script, "trail")


def _ledger(rng: random.Random, ident: str) -> MultiTask:
    names = _Names(rng)
    stock, changes, out = names.file("stock"), names.file("changes"), names.file("total")
    person = rng.choice(PEOPLE)
    goods = rng.sample(GOODS, 6)
    quantity = {item: rng.randint(12, 60) for item in goods}
    price = {item: rng.randint(3, 29) for item in goods}
    lines, after = [], dict(quantity)
    for item in rng.sample(goods, 4):
        if rng.random() < 0.5:
            amount = rng.randint(2, after[item] - 1)
            after[item] -= amount
            lines.append(f"sold {amount} {item}")
        else:
            amount = rng.randint(5, 40)
            after[item] += amount
            lines.append(f"received {amount} {item}")
    total = str(sum(after[item] * price[item] for item in goods))
    files = {stock: "item,quantity,unit_price\n" + "\n".join(
        f"{item},{quantity[item]},{price[item]}" for item in goods), changes: "\n".join(lines)}
    question = (
        f"{stock} lists items with a quantity and a unit price. {changes} lists what has "
        "been sold and received since. Apply those changes to the quantities, then work "
        "out the total stock value: quantity times unit price, summed over all items. "
        f"Write that total to {out} as just the number, send {person} a message with "
        "just the number, and then reply with just the number.")
    script = [("read_file", {"path": stock}), ("read_file", {"path": changes}),
              ("write_file", {"path": out, "text": total}),
              ("send_message", {"to": person, "text": total}), ("response", {"text": total})]
    return MultiTask(ident, question, files, total, {**files, out: total}, [(person, total)],
                     script, "ledger")


def _cleanup(rng: random.Random, ident: str) -> MultiTask:
    names = _Names(rng)
    manifest, keep = names.file("manifest"), names.file("keep")
    listed = [names.file() for _ in range(6)]
    obsolete = rng.sample(listed, rng.choice([3, 4]))
    active = [name for name in listed if name not in obsolete]
    kept = [rng.choice(obsolete), rng.choice(active)]
    rng.shuffle(kept)
    doomed = [name for name in listed if name in obsolete and name not in kept]
    files = {name: "data" for name in listed}
    files[manifest] = "\n".join(f"{name}: {'obsolete' if name in obsolete else 'active'}"
                                for name in listed)
    files[keep] = "\n".join(kept)
    question = (
        f"{manifest} marks each file as active or obsolete. Delete every file it marks "
        f"obsolete, except any file named in {keep}: those must stay whatever the "
        "manifest says. Delete nothing else. Then reply with just the number of files "
        "you deleted.")
    script = [("read_file", {"path": manifest}), ("read_file", {"path": keep})]
    script += [("delete_file", {"path": name}) for name in doomed]
    script.append(("response", {"text": str(len(doomed))}))
    final = {name: text for name, text in files.items() if name not in doomed}
    return MultiTask(ident, question, files, str(len(doomed)), final, [], script, "cleanup")


def _routing(rng: random.Random, ident: str) -> MultiTask:
    names = _Names(rng)
    tickets = [names.file("ticket"), names.file("ticket")]
    routing, out = names.file("routing"), names.file("assigned")
    categories = ["billing", "shipping", "accounts", "returns"]
    people = rng.sample(PEOPLE, 8)
    owner, deputy = dict(zip(categories, people[:4])), dict(zip(categories, people[4:]))
    files = {routing: "owners\n" + "\n".join(f"{c}: {owner[c]}" for c in categories)
             + "\n\ndeputies (a deputy takes every ticket marked priority: high)\n"
             + "\n".join(f"{c}: {deputy[c]}" for c in categories)}
    priorities = rng.choice([("high", "normal"), ("normal", "high"), ("high", "high")])
    assigned, sent = [], []
    for ticket, priority in zip(tickets, priorities):
        category, ref = rng.choice(categories), f"TCK-{rng.randint(1000, 9999)}"
        files[ticket] = f"ref: {ref}\ncategory: {category}\npriority: {priority}"
        person = deputy[category] if priority == "high" else owner[category]
        assigned.append(person)
        sent.append((person, ref))
    written = ",".join(assigned)
    question = (
        f"Tickets {tickets[0]} and {tickets[1]} each need assigning, and {routing} says "
        "who takes which ticket. For each ticket, send the right person a message "
        "containing just the ticket's ref. Then write the two names to "
        f"{out}, first ticket first, separated by a comma, and reply with the word done.")
    script = [("read_file", {"path": name}) for name in tickets + [routing]]
    script += [("send_message", {"to": to, "text": text}) for to, text in sent]
    script += [("write_file", {"path": out, "text": written}), ("response", {"text": "done"})]
    return MultiTask(ident, question, files, "done", {**files, out: written}, sent, script,
                     "routing")


def _recount(rng: random.Random, ident: str) -> MultiTask:
    names = _Names(rng)
    one, two = names.file("count"), names.file("count")
    recount, out = names.file("recount"), names.file("total")
    goods = rng.sample(GOODS, 7)
    first = {item: rng.randint(14, 96) for item in goods}
    second = dict(first)
    differ = rng.sample(goods, rng.choice([2, 3, 4]))
    for item in differ:
        second[item] = first[item] + rng.choice([-9, -4, -2, 3, 5, 11])
    # The recount also names one item the counts agreed on: its count is already settled.
    settled = rng.choice([item for item in goods if item not in differ])
    again = {item: first[item] + rng.choice([-3, -1, 1, 2]) for item in differ + [settled]}
    right = {item: again[item] if item in differ else first[item] for item in goods}
    total = str(sum(right.values()))
    files = {one: "\n".join(f"{item}: {first[item]}" for item in goods),
             two: "\n".join(f"{item}: {second[item]}" for item in goods),
             recount: "\n".join(f"{item}: {again[item]}" for item in sorted(again))}
    question = (
        f"{one} and {two} are two counts of the same shelves. Where they agree, that is "
        f"the count. Where they differ, the right count is the one in {recount}. Write "
        f"the total of the right counts over all items to {out} as just the number, and "
        "then reply with just the number of items on which the two counts differed.")
    script = [("read_file", {"path": name}) for name in (one, two, recount)]
    script += [("write_file", {"path": out, "text": total}),
               ("response", {"text": str(len(differ))})]
    return MultiTask(ident, question, files, str(len(differ)), {**files, out: total}, [],
                     script, "recount")


_MAKERS = (_trail, _ledger, _cleanup, _routing, _recount)


def make(rng: random.Random, index: int) -> MultiTask:
    form = (index // 2) % len(_MAKERS)      # pairs share a form, so both splits get every form
    return _MAKERS[form](rng, f"multi-{index:04d}")
