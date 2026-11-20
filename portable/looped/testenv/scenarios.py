"""Scripted scenarios for the isolated Looped Mode tests.

Each scenario scripts the stub model's replies in the order the agent will ask
for them, sends chat messages, and states what must be observed.

Shell commands compute their marker (``echo A$((1000+11))`` prints ``A1011``),
so a marker in the chat log proves the command ran: the command text alone
never contains it.
"""

from __future__ import annotations


def step(tool: str, headline: str = "Next step", **args) -> dict:
    return {"thoughts": ["Scripted test step."], "headline": headline,
            "tool_name": tool, "tool_args": args}


def shell(expression: str) -> dict:
    return step("code_execution_tool", "Running a shell command",
                runtime="terminal", session=0, code=f"echo {expression}")


def final(text: str) -> dict:
    return step("response", "Answering", text=text)


LONG_A = "Draft one says the report has three parts. " * 12
LONG_B = "Draft two says the report has four parts. " * 12

SCENARIOS: dict[str, dict] = {
    "01_agree": {
        "description": "Two passes agree; one tool call runs once.",
        "settings": {"mode": "always"},
        "main": [shell("A$((1000+11))"), shell("A$((1000+11))"),
                 final("DONE_AGREE"), final("DONE_AGREE")],
        "messages": [{"text": "Print the marker.", "wait_for": "DONE_AGREE"}],
        "expect": {"main_calls": 4, "log_contains": ["A1011"],
                   "heading_contains": ["Looped: both passes agree"],
                   "extra_calls": 2, "reread": True},
    },
    "02_tiebreak": {
        "description": "Passes disagree; a third decides; only the winner runs.",
        "settings": {"mode": "always"},
        "main": [shell("P$((1200+12))"), shell("B$((2000+22))"), shell("B$((2000+22))"),
                 final("DONE_TIEBREAK"), final("DONE_TIEBREAK")],
        "messages": [{"text": "Print the marker.", "wait_for": "DONE_TIEBREAK"}],
        "expect": {"main_calls": 5, "extra_calls": 3, "log_contains": ["B2022"],
                   "log_lacks": ["P1212"],
                   "heading_contains": ["Looped: passes disagreed, third pass decided"]},
    },
    "03_invalid_first": {
        "description": "A malformed first pass is replaced by a valid second.",
        "settings": {"mode": "always"},
        "main": ["I will now run the command without any JSON.", shell("C$((3000+33))"),
                 final("DONE_INVALID"), final("DONE_INVALID")],
        "messages": [{"text": "Print the marker.", "wait_for": "DONE_INVALID"}],
        "expect": {"main_calls": 4, "log_contains": ["C3033"],
                   "heading_contains": ["Looped: first pass was invalid, used the second"]},
    },
    "04_auto_skips_ordinary_steps": {
        "description": "Auto mode with only the risky-tool checkpoint leaves a plain answer alone.",
        "settings": {"mode": "auto", "auto": {"checkpoints": ["risky_tool"]}},
        "main": [final("DONE_AUTO_SKIP")],
        "messages": [{"text": "Say the word.", "wait_for": "DONE_AUTO_SKIP"}],
        "expect": {"main_calls": 1, "heading_lacks": ["Looped"]},
    },
    "05_auto_checks_risky_tool": {
        "description": "Auto mode checks a tool with side effects, not the final answer.",
        "settings": {"mode": "auto", "auto": {"checkpoints": ["risky_tool"]}},
        "main": [shell("R$((7000+77))"), shell("R$((7000+77))"), final("DONE_AUTO_RISKY")],
        "messages": [{"text": "Print the marker.", "wait_for": "DONE_AUTO_RISKY"}],
        "expect": {"main_calls": 3, "log_contains": ["R7077"],
                   "heading_contains": ["Looped: both passes agree"]},
    },
    "06_fuse_final_answers": {
        "description": "Two long final answers that differ are merged in one pass.",
        "settings": {"mode": "always"},
        "main": [final(LONG_A), final(LONG_B), final("FUSED_ANSWER_OK")],
        "messages": [{"text": "Describe the report.", "wait_for": "FUSED_ANSWER_OK"}],
        "expect": {"main_calls": 3, "fuse": True,
                   "heading_contains": ["Looped: merged two drafts of the answer"]},
    },
    "07_slash_arms_one_turn": {
        "description": "/looped arms one message in manual mode, then disarms.",
        "settings": {"mode": "manual"},
        "main": [final("DONE_SLASH"), final("DONE_SLASH"), final("DONE_PLAIN")],
        "messages": [{"text": "/looped Say the first word.", "wait_for": "DONE_SLASH"},
                     {"text": "Say the second word.", "wait_for": "DONE_PLAIN"}],
        "expect": {"main_calls": 3, "slash_token_in_prompt": False, "armed": False,
                   "heading_contains": ["Looped: both passes agree"]},
    },
    "08_slash_sets_chat_mode": {
        "description": "/looped auto sets the chat's mode without running the agent.",
        "settings": {"mode": "manual"},
        "main": [],
        "messages": [{"text": "/looped auto", "wait_for": None, "settle": 8}],
        "expect": {"main_calls": 0, "mode": "auto"},
    },
    "09_second_look_after_error": {
        "description": "A failed tool arms a second look at the next step.",
        "settings": {"mode": "auto", "auto": {"checkpoints": ["after_error"]}},
        "main": [step("code_execution_tool", "Listing a folder", runtime="terminal", session=0,
                      code="ls /definitely/not/a/real/folder"),
                 shell("E$((4000+44))"), shell("E$((4000+44))"), final("DONE_RETRY")],
        "messages": [{"text": "List the folder, then print the marker.", "wait_for": "DONE_RETRY"}],
        "expect": {"main_calls": 4, "log_contains": ["E4044"], "retry_note": True,
                   "heading_contains": ["Looped: both passes agree"]},
    },
    "10_off_changes_nothing": {
        "description": "With mode off the plugin makes no extra calls and adds nothing.",
        "settings": {"mode": "off"},
        "main": [shell("O$((8000+88))"), final("DONE_OFF")],
        "messages": [{"text": "/looped Print the marker.", "wait_for": "DONE_OFF"}],
        "expect": {"main_calls": 2, "log_contains": ["O8088"], "heading_lacks": ["Looped"],
                   "reread": False, "slash_token_in_prompt": False},
    },
    "11_reason_twice": {
        "description": "Experimental: the second pass sees the draft and revises it.",
        "settings": {"mode": "always", "strategies": {"deepen": {"enabled": True}}},
        "main": [shell("D$((5000+55))"), shell("F$((6000+66))"),
                 final("DONE_DEEPEN"), final("DONE_DEEPEN")],
        "messages": [{"text": "Print the marker.", "wait_for": "DONE_DEEPEN"}],
        "expect": {"main_calls": 4, "deepen": True, "log_contains": ["F6066"],
                   "log_lacks": ["D5055"],
                   "heading_contains": ["Looped: second pass revised the draft"]},
    },
    "12_parallel_planning": {
        "description": "Experimental: two tool-free plans are merged into one guidance note.",
        "settings": {"mode": "always",
                     "strategies": {"plan_branch": {"enabled": True}, "agree": {"enabled": False}}},
        "plan": ["1. alpha", "1. beta", "1. MERGED_PLAN_STEP"],
        "main": [final("DONE_PLAN")],
        "messages": [{"text": "Plan and answer.", "wait_for": "DONE_PLAN"}],
        "expect": {"main_calls": 1, "plan_calls": 3, "plan_note": True},
    },
}
