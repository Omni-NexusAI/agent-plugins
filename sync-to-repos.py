#!/usr/bin/env python3
"""Preview cataloged packages or propose one sync to a standalone repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "catalog.json"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NAME_PATTERN = re.compile(r"^name:\s*([A-Za-z0-9_]+)\s*$", re.MULTILINE)


class SyncError(Exception):
    pass


def run(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        args, cwd=cwd, check=True, text=True, encoding="utf-8",
        stdout=subprocess.PIPE,
    )
    return result.stdout.strip()


def catalog_entries() -> list[dict]:
    try:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SyncError(f"Cannot read catalog: {error}") from error
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("plugins"), list):
        raise SyncError("Unsupported catalog schema")

    entries = catalog["plugins"]
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SyncError("Every catalog plugin entry must be an object")
        plugin_id = entry.get("id")
        source_name = entry.get("source")
        if not isinstance(plugin_id, str) or not re.fullmatch(r"[A-Za-z0-9_]+", plugin_id):
            raise SyncError(f"Invalid plugin ID: {plugin_id!r}")
        if plugin_id in seen:
            raise SyncError(f"Duplicate plugin ID: {plugin_id}")
        seen.add(plugin_id)
        if source_name != f"plugins/{plugin_id}":
            raise SyncError(f"{plugin_id}: source must be plugins/{plugin_id}")
        source = ROOT / source_name
        if source.is_symlink() or not source.is_dir() or not source.resolve().is_relative_to(ROOT):
            raise SyncError(f"{plugin_id}: source directory is missing or unsafe")
        manifest = source / "plugin.yaml"
        if not manifest.is_file() or manifest.is_symlink():
            raise SyncError(f"{plugin_id}: plugin.yaml is missing or unsafe")
        match = NAME_PATTERN.search(manifest.read_text(encoding="utf-8"))
        if not match or match.group(1) != plugin_id:
            raise SyncError(f"{plugin_id}: manifest name does not match installed folder")
        if not isinstance(entry.get("frameworks"), list) or not entry["frameworks"]:
            raise SyncError(f"{plugin_id}: framework compatibility is missing")
        if entry.get("status") not in {"active", "development", "historical"}:
            raise SyncError(f"{plugin_id}: invalid status")
        destination = entry.get("distribution_repository")
        if destination is not None and (
            not isinstance(destination, str) or not REPO_PATTERN.fullmatch(destination)
        ):
            raise SyncError(f"{plugin_id}: invalid distribution repository")
        if entry["status"] != "active" and destination is not None:
            raise SyncError(f"{plugin_id}: non-active source cannot have a destination")
        preserved = entry.get("preserve_destination_paths", [])
        if not isinstance(preserved, list) or any(
            not isinstance(item, str)
            or PurePosixPath(item).is_absolute()
            or ".." in PurePosixPath(item).parts
            or item in {"", "."}
            for item in preserved
        ):
            raise SyncError(f"{plugin_id}: invalid destination-only path")

    packages = {path.name for path in (ROOT / "plugins").iterdir()
                if path.is_dir() and (path / "plugin.yaml").is_file()}
    if seen != packages:
        raise SyncError(
            f"Catalog does not match package directories: "
            f"missing={sorted(packages - seen)}, extra={sorted(seen - packages)}"
        )
    return entries


def tracked_source_files(entry: dict) -> list[tuple[Path, Path]]:
    source_name = entry["source"]
    output = subprocess.run(
        ["git", "ls-files", "-z", "--", source_name], cwd=ROOT,
        check=True, stdout=subprocess.PIPE,
    ).stdout
    files: list[tuple[Path, Path]] = []
    prefix = source_name + "/"
    for raw_name in output.split(b"\0"):
        if not raw_name:
            continue
        tracked_name = raw_name.decode("utf-8")
        if not tracked_name.startswith(prefix):
            raise SyncError(f"Unexpected tracked path: {tracked_name}")
        relative = PurePosixPath(tracked_name[len(prefix):])
        if ".." in relative.parts or not relative.parts:
            raise SyncError(f"Unsafe tracked path: {tracked_name}")
        if relative.as_posix() in entry.get("preserve_destination_paths", []):
            continue
        source_file = ROOT / tracked_name
        if source_file.is_symlink() or not source_file.is_file():
            raise SyncError(f"Missing or unsafe tracked file: {tracked_name}")
        files.append((source_file, Path(*relative.parts)))
    return files


def preview(entries: list[dict]) -> None:
    for entry in entries:
        destination = entry["distribution_repository"]
        eligible = entry["status"] == "active" and destination is not None
        count = len(tracked_source_files(entry))
        label = f"release preview -> {destination}" if eligible else "no release destination"
        print(f"{entry['id']}: {entry['status']}; {count} tracked source files; {label}")


def publish(entry: dict) -> None:
    plugin_id = entry["id"]
    destination = entry["distribution_repository"]
    if entry["status"] != "active" or destination is None:
        raise SyncError(f"{plugin_id}: no active, verified release destination")
    if run("git", "status", "--porcelain", "--", entry["source"]):
        raise SyncError(f"{plugin_id}: commit source changes before publishing")
    files = tracked_source_files(entry)
    if not files:
        raise SyncError(f"{plugin_id}: no tracked package files")

    with tempfile.TemporaryDirectory(prefix=f"agent-plugins-{plugin_id}-") as scratch:
        checkout = Path(scratch) / "destination"
        run("gh", "repo", "clone", destination, str(checkout))
        base = run("git", "branch", "--show-current", cwd=checkout)
        if not base or run("git", "status", "--porcelain", cwd=checkout):
            raise SyncError(f"{destination}: destination checkout is not clean")
        branch = f"codex/sync-{plugin_id}-{time.strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"
        run("git", "switch", "-c", branch, cwd=checkout)

        for source_file, relative in files:
            target = checkout / relative
            if target.is_symlink() or not target.resolve().is_relative_to(checkout):
                raise SyncError(f"Unsafe destination path: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)

        run("git", "add", "--all", cwd=checkout)
        if not run("git", "diff", "--cached", "--name-only", cwd=checkout):
            print(f"{plugin_id}: standalone repository is already current")
            return
        print(run("git", "diff", "--cached", "--stat", cwd=checkout))
        account = json.loads(run("gh", "api", "user", "--jq", "{id: .id, login: .login}"))
        account_id, login = account.get("id"), account.get("login")
        if not isinstance(account_id, int) or not isinstance(login, str) or not login:
            raise SyncError("Cannot determine the authenticated GitHub commit author")
        run(
            "git", "-c", f"user.name={login}",
            "-c", f"user.email={account_id}+{login}@users.noreply.github.com",
            "commit", "-m", f"Sync {plugin_id} from Agent Plugins", cwd=checkout,
        )
        run("git", "push", "--set-upstream", "origin", branch, cwd=checkout)
        body = (
            f"Sync the tracked {plugin_id} package from Omni-NexusAI/agent-plugins.\n\n"
            "Destination-only files remain unchanged. Review this source update before merging.\n"
        )
        body_file = Path(scratch) / "pr-body.md"
        body_file.write_text(body, encoding="utf-8")
        url = run(
            "gh", "pr", "create", "--repo", destination, "--base", base,
            "--head", branch, "--title", f"Sync {plugin_id} from Agent Plugins",
            "--body-file", str(body_file), cwd=checkout,
        )
        print(f"Review pull request: {url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", help="Catalog plugin ID to preview or publish")
    parser.add_argument("--publish", action="store_true", help="Push a review branch and open a PR")
    args = parser.parse_args()
    try:
        entries = catalog_entries()
        selected = [entry for entry in entries if entry["id"] == args.plugin] if args.plugin else entries
        if args.plugin and not selected:
            raise SyncError(f"Unknown plugin: {args.plugin}")
        if args.publish:
            if len(selected) != 1:
                raise SyncError("--publish requires one explicit --plugin selection")
            publish(selected[0])
        else:
            preview(selected)
        return 0
    except (SyncError, subprocess.CalledProcessError, OSError, UnicodeError, ValueError) as error:
        print(f"sync-to-repos: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
