# Enhanced MCP Config historical source

## Purpose

`_enhanced_mcp_config` is retained as the Agentspine GPU-pre historical
snapshot. The current source record excludes it from migration and release
copies. Its manifest and runtime files remain unchanged for reference.

## Local Contracts

- Treat this directory as historical evidence, not an active distribution.
- Do not publish it through the monorepo sync command.
- Preserve its installed name and internal source relationships when studying
  or updating the snapshot deliberately.
- Do not restore its `overrides/a0` payload to an Agent Zero or Agentspine
  runtime as part of repository maintenance.

## Verification

- Confirm `catalog.json` continues to mark this source historical and gives it
  no distribution destination.
- Check `CONTAINER_SYNC.md` before making any source behavior claim.
