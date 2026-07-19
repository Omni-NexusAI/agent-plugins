from pathlib import Path
from helpers import files
from helpers.api import ApiHandler, Request, Response
from usr.plugins.browser_session_sync.helpers.session_sync import (
    MANIFEST_FILE_NAME,
    delete_session_file,
    enforce_retention,
    load_config,
    load_manifest,
    load_snapshot,
    repair_manifest,
    save_config,
)

SAVE_DIR = Path(files.get_abs_path("usr", "browser_sessions"))


class SessionsList(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        action = input.get("action", "list")
        
        if action == "list":
            return self._list_sessions()
        elif action == "delete":
            filename = input.get("filename", "")
            return self._delete_session(filename)
        elif action == "delete_all":
            return self._delete_all()
        elif action == "stats":
            return self._get_stats()
        elif action == "prune":
            keep_count = int(input.get("keep_count", 10))
            return self._prune_oldest(keep_count)
        elif action == "set_max_size":
            max_mb = float(input.get("max_mb", 50))
            return self._enforce_max_size(max_mb)
        elif action == "get_config":
            return {"ok": True, "config": load_config()}
        elif action == "save_config":
            return {"ok": True, "config": save_config(input.get("config") or input)}
        
        return {"ok": False, "error": f"Unknown action: {action}"}
    
    def _list_sessions(self) -> dict:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        manifest = repair_manifest()
        sessions = []
        for f in sorted(self._session_files(), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                snapshot = load_snapshot(f)
                sessions.append(self._session_info(f, snapshot, manifest))
            except Exception:
                sessions.append(self._session_info(f, None, manifest))
        stats = self._compute_stats(sessions)
        return {"ok": True, "sessions": sessions, "stats": stats, "config": load_config()}
    
    def _session_info(self, f: Path, snapshot: dict | None, manifest: dict) -> dict:
        size = f.stat().st_size
        context_id = self._context_id_for_file(f.name, manifest)
        info = {
            "name": f.name,
            "context_id": context_id,
            "size": size,
            "size_str": self._format_size(size),
            "cookies": 0,
            "origins": 0,
            "domains": [],
            "tabs": [],
            "tab_count": 0,
            "is_current": self._is_current_context_file(f.name, manifest),
            "is_global_current": self._is_global_current_file(f.name, manifest),
            "date": f.stat().st_mtime,
            "date_str": self._format_date(f.stat().st_mtime),
        }
        if snapshot:
            context_state = snapshot.get("context_state") or {}
            tabs = snapshot.get("tabs") or []
            info["tabs"] = tabs
            info["tab_count"] = int(snapshot.get("tab_count") or len(tabs))
            cookies = context_state.get("cookies", [])
            origins = context_state.get("origins", [])
            info["cookies"] = len(cookies)
            info["origins"] = len(origins)
            domains = sorted(set(c.get("domain", "") for c in cookies if c.get("domain")))
            info["domains"] = domains[:20]
            if len(domains) > 20:
                info["domains"].append(f"... and {len(domains)-20} more")
        return info
    
    def _compute_stats(self, sessions: list) -> dict:
        total_size = sum(s["size"] for s in sessions)
        total_cookies = sum(s["cookies"] for s in sessions)
        total_origins = sum(s["origins"] for s in sessions)
        total_tabs = sum(s.get("tab_count", 0) for s in sessions)
        all_domains = set()
        for s in sessions:
            for d in s.get("domains", []):
                if not d.startswith("..."):
                    all_domains.add(d)
        return {
            "total_files": len(sessions),
            "total_size": total_size,
            "total_size_str": self._format_size(total_size),
            "max_cache_mb": load_config().get("max_cache_mb"),
            "max_saved_sessions": load_config().get("max_saved_sessions"),
            "total_cookies": total_cookies,
            "total_origins": total_origins,
            "total_tabs": total_tabs,
            "unique_domains": len(all_domains),
            "current_files": sum(1 for s in sessions if s.get("is_current")),
            "global_current": next((s for s in sessions if s.get("is_global_current")), None),
        }
    
    def _get_stats(self) -> dict:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        manifest = load_manifest()
        sessions = []
        for f in self._session_files():
            sessions.append(self._session_info(f, None, manifest))
        return {"ok": True, "stats": self._compute_stats(sessions)}
    
    def _delete_session(self, filename: str) -> dict:
        if not filename or ".." in filename or "/" in filename or "\\" in filename:
            return {"ok": False, "error": "Invalid filename"}
        if delete_session_file(filename):
            return {"ok": True}
        return {"ok": False, "error": "File not found"}
    
    def _delete_all(self) -> dict:
        count = 0
        for f in self._session_files():
            f.unlink()
            count += 1
        repair_manifest()
        return {"ok": True, "deleted": count}
    
    def _prune_oldest(self, keep_count: int) -> dict:
        config = save_config({"max_saved_sessions": keep_count})
        result = enforce_retention(config)
        result["message"] = f"Retention now keeps up to {config['max_saved_sessions']} saved sessions."
        return result
    
    def _enforce_max_size(self, max_mb: float) -> dict:
        config = save_config({"max_cache_mb": max_mb})
        result = enforce_retention(config)
        result["message"] = f"Retention now keeps cache under {config['max_cache_mb']} MB."
        return result
    
    def _format_size(self, bytes_val: int) -> str:
        if bytes_val < 1024:
            return f"{bytes_val} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        else:
            return f"{bytes_val / (1024 * 1024):.2f} MB"
    
    def _format_date(self, ts: float) -> str:
        import datetime
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    def _session_files(self) -> list[Path]:
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        return [
            path
            for path in SAVE_DIR.glob("*.json")
            if path.name != MANIFEST_FILE_NAME
        ]

    def _context_id_for_file(self, filename: str, manifest: dict) -> str:
        contexts = manifest.get("contexts") if isinstance(manifest.get("contexts"), dict) else {}
        for context_id, entry in contexts.items():
            if isinstance(entry, dict) and entry.get("filename") == filename:
                return str(context_id)
        global_latest = manifest.get("global_latest")
        if isinstance(global_latest, dict) and global_latest.get("filename") == filename:
            return str(global_latest.get("context_id") or "")
        if "_" in filename:
            return filename.rsplit("_", 1)[0]
        return filename.rsplit(".", 1)[0]

    def _is_current_context_file(self, filename: str, manifest: dict) -> bool:
        contexts = manifest.get("contexts") if isinstance(manifest.get("contexts"), dict) else {}
        return any(isinstance(entry, dict) and entry.get("filename") == filename for entry in contexts.values())

    def _is_global_current_file(self, filename: str, manifest: dict) -> bool:
        global_latest = manifest.get("global_latest")
        return isinstance(global_latest, dict) and global_latest.get("filename") == filename
