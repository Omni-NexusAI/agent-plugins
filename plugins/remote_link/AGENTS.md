# Remote Link DOX

## Purpose

Optionally auto-start Agent Zero's built-in Remote Control tunnel at container boot with a selectable link provider.

## Ownership

- `plugin.yaml` owns plugin identity, manifest fields, and settings-section placement.
- `default_config.yaml` owns `auto_start` and `provider` defaults.
- `helpers/tunnel_manager.py` owns the thin client of the built-in tunnel API server; it must not spawn parallel tunnel processes.
- `extensions/python/startup_migration/` owns boot-time auto-start; it must wait for the tunnel server and reuse any running URL.
- `api/remote_link.py` owns programmatic start/stop/status routes.
- `webui/config.html` owns only the auto-start toggle and provider select; start/stop/status stay in the built-in Remote Control panel.

## Local Contracts

- Never hardcode a tunnel port; resolve it from runtime/dotenv with a 55520 fallback.
- Supported providers must mirror `helpers/tunnel_manager.py`: `cloudflared`, `tailscale`, `microsoft`, `serveo`.
- Auto-start must check status first and never regenerate a running tunnel URL.
- Do not add sidebar widgets or duplicate the built-in Remote Control UI.
- Keep README, manifest, default config, and behavior aligned.

## Verification

- Parse touched Python files and import the helper, API handler, and startup extension.
- Check live read-only status against the tunnel server without stopping an active tunnel.

## Child DOX Index

No child DOX files.
