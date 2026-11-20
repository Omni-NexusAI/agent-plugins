"""Turn a model's raw step into a comparable candidate.

Two candidates agree when their canonical keys are equal: same tool, same
arguments after cosmetic differences (key order, trailing whitespace, line
endings, ``1`` versus ``1.0``) are removed.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .types import Candidate

FINAL_TOOLS: tuple[str, ...] = ("response",)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_SPACES = re.compile(r"\s+")


def _balanced_object(text: str) -> str | None:
    """Return the first complete ``{...}`` in ``text``, honouring strings."""
    start = text.find("{")
    if start < 0:
        return None
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def parse_step(text: str) -> dict[str, Any] | None:
    """Parse the JSON object a model emitted, tolerating common damage."""
    if not isinstance(text, str) or "{" not in text:
        return None
    attempts = []
    balanced = _balanced_object(text)
    if balanced:
        attempts.append(balanced)
    end = text.rfind("}")
    if end > text.find("{"):
        attempts.append(text[text.find("{"):end + 1])
    for attempt in attempts:
        for variant in (attempt, _TRAILING_COMMA.sub(r"\1", attempt)):
            try:
                value = json.loads(variant, strict=False)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                return value
    return None


def _normalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalise(item) for key, item in sorted(
            value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if len(lines) <= 1:
            return _SPACES.sub(" ", lines[0]).strip() if lines else ""
        return "\n".join(lines)
    return value


def normalise_answer(text: str) -> str:
    """Loose form of a final answer, for exact-match voting on short answers."""
    cleaned = _SPACES.sub(" ", str(text)).strip().lower()
    # Strip wrapping markup and closing punctuation in any order ("**42**.").
    return cleaned.strip("*_`\"' .!")


def final_text(tool_args: dict[str, Any]) -> str:
    for name in ("text", "message", "answer", "response"):
        value = tool_args.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return json.dumps(_normalise(tool_args), sort_keys=True, ensure_ascii=False)


def canonical_key(tool_name: str, tool_args: dict[str, Any], final: bool = False) -> str:
    name = str(tool_name).strip().lower()
    if final:
        return "final:" + normalise_answer(final_text(tool_args))
    return name + ":" + json.dumps(_normalise(tool_args), sort_keys=True,
                                   ensure_ascii=False, separators=(",", ":"))


def build_candidate(
    raw: str,
    reasoning: str = "",
    *,
    label: str = "A",
    parser: Callable[[str], Any] | None = None,
    final_tools: tuple[str, ...] = FINAL_TOOLS,
) -> Candidate:
    """Parse ``raw`` and classify it. Parsing problems make it ``invalid``."""
    candidate = Candidate(raw=raw if isinstance(raw, str) else "",
                          reasoning=reasoning or "", label=label)
    parsed = None
    try:
        parsed = (parser or parse_step)(candidate.raw)
    except Exception:
        parsed = None
    if not isinstance(parsed, dict):
        candidate.problems.append("unparsed")
        return candidate
    candidate.parsed = parsed
    name = parsed.get("tool_name", parsed.get("tool"))
    args = parsed.get("tool_args", parsed.get("args"))
    if not isinstance(name, str) or not name.strip():
        candidate.problems.append("no_tool_name")
        return candidate
    candidate.tool_name = name.strip()
    if not isinstance(args, dict):
        candidate.problems.append("args_not_object")
        return candidate
    candidate.tool_args = args
    is_final = candidate.tool_name.lower().split(":")[0] in final_tools
    candidate.kind = "final" if is_final else "action"
    candidate.key = canonical_key(candidate.tool_name, args, final=is_final)
    return candidate
