# Remote Link

Optionally auto-start Agent Zero's **built-in Remote Control** tunnel when the
container boots, and choose which link provider it uses.

This plugin does **not** run its own tunnel and does **not** duplicate the Remote
Control UI. It drives the same remote-control system the WebUI
**Settings → Remote Control** panel uses (the tunnel API server `run_tunnel.py`
reached via `/tunnel_proxy`). Start, stop, and live status stay in that built-in
panel; this plugin only configures boot-time auto-start and the provider.

## What the plugin provides

- **Auto-start on/off toggle** — enable or disable boot-time auto-start.
- **Selectable link provider** — `cloudflared`, `tailscale`, `microsoft`, `serveo`
  (same list as the built-in panel).
- **Boot-time startup extension** — waits for the tunnel server, then reuses any
  already-running tunnel URL instead of generating a new one.

## Configuration

| Setting | Default | Description |
|---|---|---|
| `auto_start` | `false` | Start Remote Control automatically on container boot |
| `provider` | `tailscale` | Provider used by auto-start: `cloudflared`, `tailscale`, `microsoft`, `serveo` |

## URL stability

- **Tailscale** — stable MagicDNS URL (e.g. `https://<host>.tail<net>.ts.net/`)
that persists across reboots. Best fit for a fixed address.
- **Cloudflare / Serveo** — generate a new random URL each fresh start.
- **Microsoft Dev Tunnels** — stable per tunnel ID after GitHub login.

Because auto-start checks status first, a running tunnel is never replaced, so
your existing URL survives container restarts.

## How it works

```
container boot
  → run_tunnel.py server starts (port 55520)
  → this plugin's startup extension waits for the server, then:
       if Remote Control already running → reuse URL
       else → POST {action: create, provider: <chosen>} to the tunnel server
```

## API (programmatic control)

```
POST /api/plugins/remote_link/remote_link
{ "action": "start" | "stop" | "status", "provider": "tailscale" }   // provider optional
```

## Files

```
remote_link/
  plugin.yaml
  default_config.yaml
  hooks.py
  api/remote_link.py
  helpers/tunnel_manager.py            # thin client of the built-in tunnel server
  extensions/python/startup_migration/_10_remote_link_autostart.py
  webui/config.html                    # auto-start toggle + provider select only
```
