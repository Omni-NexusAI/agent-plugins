"""Bounded observer of live intervention events while the host model works."""

from __future__ import annotations

import asyncio
import time

from usr.plugins.system_1.helpers.runtime import client_for, config_for
from usr.plugins.system_1.helpers.system_1_core import DecisionError


TASK_KEY = "system_1_monitor_task"
REQUEST_KEY = "system_1_interruption_requested"


async def monitor(agent, section: dict, policy: dict) -> None:
    """Observe only new native interventions; ask the host loop to consume them."""
    interval = max(0.1, min(10.0, float(policy.get("monitor_interval_seconds", 0.5))))
    checks = max(1, min(100, int(policy.get("monitor_max_checks", 20))))
    duration = max(1.0, min(300.0, float(policy.get("monitor_max_seconds", 30))))
    deadline = time.monotonic() + duration
    last_event = None
    try:
        client = client_for(section, policy)
    except (DecisionError, ValueError, TypeError, OSError):
        return
    while checks > 0 and time.monotonic() < deadline:
        await asyncio.sleep(interval)
        if not config_for(agent, "main"):
            return
        event = getattr(agent, "intervention", None)
        if not event or event == last_event:
            continue
        last_event = event
        checks -= 1
        try:
            result = await client.choose(str(event)[:1000], {
                "host_interrupt": "New user input should interrupt or reprioritize the current work.",
                "host_continue": "Current work may continue until the host handles this event."})
            if result.choice == "host_interrupt" and result.confidence >= float(policy.get("min_choice_probability", 0.85)):
                agent.set_data(REQUEST_KEY, True)
        except (DecisionError, ValueError, TypeError, OSError):
            continue


def start(agent) -> None:
    old = agent.get_data(TASK_KEY)
    if old and not old.done():
        return
    settings = config_for(agent, "main")
    if settings:
        section, policy = settings
        agent.set_data(TASK_KEY, asyncio.create_task(monitor(agent, section, policy)))


def stop(agent) -> None:
    task = agent.get_data(TASK_KEY)
    if task and not task.done():
        task.cancel()
    agent.set_data(TASK_KEY, None)
    agent.set_data(REQUEST_KEY, False)
