# Agent Plugins

Source repository for Agent Zero and Agentspine plugins, with a place for future
plugins that support more than one agent framework. Existing installed packages
remain under `plugins/<id>`; their directory names and `plugin.yaml` identities
are unchanged.

## Plugin catalog

[`catalog.json`](catalog.json) records each package's source path, supported
frameworks, development status, and verified standalone distribution repository.
A missing distribution repository means no automatic publication destination has
been verified.

| Source | Compatibility | Status |
| --- | --- | --- |
| [`browser_session_sync`](plugins/browser_session_sync/) | Agent Zero and compatible Agentspine hosts | Active; verified [standalone repository](https://github.com/Omni-NexusAI/browser_session_sync) |
| [`provider_profiles`](plugins/provider_profiles/) | Agent Zero and compatible Agentspine hosts | Active |
| [`_enhanced_speech`](plugins/_enhanced_speech/) | Agent Zero and compatible Agentspine hosts | Active; voice compatibility changes are under review |
| [`_agentspine_identity`](plugins/_agentspine_identity/) | Agentspine | Active, Agentspine-specific |
| [`_multi_source_updater`](plugins/_multi_source_updater/) | Agentspine | Active, Agentspine-specific |
| [`ai_link_bridge`](plugins/ai_link_bridge/) | Agent Zero and Agentspine integration target | Development scaffold; task dispatch is not implemented |
| [`_enhanced_mcp_config`](plugins/_enhanced_mcp_config/) | Historical Agentspine snapshot | Historical source; excluded from releases |

The [source sync record](CONTAINER_SYNC.md) describes the origins and
compatibility boundaries of the existing packages. The separate
[Agent Skills repository](https://github.com/Omni-NexusAI/agent-skills) is not
part of this monorepo.

## Package layout

- `plugins/<id>/` contains existing self-contained Agent Zero-style packages.
  Install a compatible package by copying its folder into the host's plugin
  directory, preserving its folder name.
- [`portable/`](portable/) is for future plugin sources with shared `core/`
  logic and framework-specific `adapters/<framework>/` code. An adapter's
  distribution must include the shared code it needs. The monorepo is never a
  runtime dependency of an installed package.

Convo and System 1 are planned portable plugins. The auxiliary model-role
extension is planned as an Agent Zero package. This repository foundation does
not contain their implementations.

## Standalone repository sync

`sync-to-repos.sh` reads the catalog. Its default action is a local preview of
release eligibility and tracked source files; it makes no remote changes.

```bash
./sync-to-repos.sh
./sync-to-repos.sh --plugin browser_session_sync
```

Publishing requires one explicit, active plugin with a verified standalone
repository. It copies tracked source files to a review branch in that existing
repository and opens a pull request. Destination-only files are retained;
intentional removals require a separate review.

```bash
./sync-to-repos.sh --plugin browser_session_sync --publish
```

The Browser Session Sync marketplace `index.yaml` in its standalone repository
keeps that repository as its source. The copy in this monorepo links here and is
not transferred by the sync command.

## Maintenance

Follow the [`AGENTS.md`](AGENTS.md) hierarchy before editing and after changing
repository or plugin contracts. Keep runtime caches, installed settings, logs,
and secrets out of source control. This repository is [MIT licensed](LICENSE).
