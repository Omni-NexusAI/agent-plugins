# Telegram Harness Notify Plugin

Sends Telegram notifications when the Agent Harness creates a checkpoint or blocks a risky action.

## Purpose

Without this plugin, an A0 agent hitting a harness checkpoint will wait indefinitely for user approval because there's no proactive notification mechanism. This plugin sends an instant Telegram message to the configured recipient at the moment the checkpoint is created or a risky action is auto-blocked.

## Installation

Copy `telegram_harness_notify/` into the target instance's `usr/plugins/` directory and enable it in the Plugin Manager.

## How It Works

The plugin provides `helpers/telegram_notify.py` containing a `notify_checkpoint_pending()` function that sends a Telegram Bot API message via `urllib` (no dependencies). The Agent Harness files (`harness_checkpoint.py` and `_20_harness_guardrails.py`) detect the plugin's presence via `try/except ImportError` — if the plugin is installed, notifications fire automatically; if it's absent, the notification call silently becomes a no-op and the harness continues normally.

## Configuration

Edit `helpers/telegram_notify.py` to update:
- `TELEGRAM_BOT_TOKEN`: Your bot token from @BotFather
- `TELEGRAM_CHAT_ID`: The target chat/user ID

## Files

| File | Purpose |
|---|---|
| `plugin.yaml` | Plugin manifest |
| `helpers/telegram_notify.py` | Telegram notification helper |
| `README.md` | This file |

## Graceful Degradation

Even when this plugin is not installed, the Agent Harness continues to work without errors — the notification simply doesn't fire. No tracebacks, no crashes.
