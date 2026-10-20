from __future__ import annotations

import itertools
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from .loader import VECTORS, load_helper

store_mod = load_helper("favorites_store")
FavoritesError = store_mod.FavoritesError
VEC = json.loads((VECTORS / "identity_vectors.json").read_text(encoding="utf-8"))


def ticking_clock(start=1000.0):
    counter = itertools.count()
    return lambda: start + next(counter)


class IdentityVectors(unittest.TestCase):
    def test_canonical_base(self):
        for source, expected in VEC["canonical_base"]:
            with self.subTest(source=source):
                self.assertEqual(store_mod.canonical_base(source), expected)

    def test_invalid_base(self):
        for source, code in VEC["invalid_base"]:
            with self.subTest(source=source):
                with self.assertRaises(FavoritesError) as ctx:
                    store_mod.canonical_base(source)
                self.assertEqual(ctx.exception.code, code)

    def test_same_identity(self):
        def ident(spec):
            entry = store_mod.clean_entry(spec["type"], spec["provider"], spec["api_base"], spec["name"])
            return store_mod.identity_of(entry)

        for a, b, same in VEC["same_identity"]:
            with self.subTest(a=a, b=b):
                self.assertEqual(ident(a) == ident(b), same)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "favorites.json"

    def store(self, **kw):
        kw.setdefault("clock", ticking_clock())
        return store_mod.FavoritesStore(self.path, **kw)


class StoreBehavior(StoreCase):
    def test_set_on_off_is_idempotent(self):
        store = self.store()
        first = store.set_favorite("chat", "OpenRouter", "", "deepseek/x", True)
        rev = first["snapshot"]["rev"]
        again = store.set_favorite("chat", "openrouter", "", "deepseek/x", True)
        self.assertEqual(again["snapshot"]["rev"], rev, "re-starring must not write")
        self.assertEqual(len(again["snapshot"]["types"]["chat"]), 1)
        off = store.set_favorite("chat", "openrouter", "", "deepseek/x", False)
        self.assertFalse(off["starred"])
        self.assertEqual(off["snapshot"]["types"]["chat"], [])
        off2 = store.set_favorite("chat", "openrouter", "", "deepseek/x", False)
        self.assertEqual(off2["snapshot"]["rev"], off["snapshot"]["rev"])

    def test_recency_order_and_touch(self):
        store = self.store()
        for name in ("a", "b", "c"):
            store.set_favorite("chat", "other", "http://h:1/v1", name, True)
        names = lambda: [i["name"] for i in store.snapshot()["types"]["chat"]]
        self.assertEqual(names(), ["c", "b", "a"], "newest star first (starring counts as use)")
        result = store.touch("chat", "other", "http://h:1", "a")  # same identity via canonical base
        self.assertTrue(result["touched"])
        self.assertEqual(names(), ["a", "c", "b"])
        self.assertFalse(store.touch("chat", "other", "http://h:1", "missing")["touched"])

    def test_types_are_independent_and_identity_includes_endpoint(self):
        store = self.store()
        store.set_favorite("chat", "other", "http://a:1", "m", True)
        store.set_favorite("utility", "other", "http://a:1", "m", True)
        store.set_favorite("chat", "other", "http://b:1", "m", True)
        snap = store.snapshot()["types"]
        self.assertEqual(len(snap["chat"]), 2)
        self.assertEqual(len(snap["utility"]), 1)
        self.assertEqual(snap["vision"], [])

    def test_limit_is_explicit(self):
        store = self.store(max_per_type=2)
        store.set_favorite("chat", "p", "", "a", True)
        store.set_favorite("chat", "p", "", "b", True)
        with self.assertRaises(FavoritesError) as ctx:
            store.set_favorite("chat", "p", "", "c", True)
        self.assertEqual(ctx.exception.code, "limit_reached")
        store.set_favorite("utility", "p", "", "c", True)  # other types unaffected

    def test_persistence_and_rev(self):
        a = self.store()
        a.set_favorite("embedding", "huggingface", "", "all-MiniLM", True)
        b = self.store()
        snap = b.snapshot()
        self.assertEqual(snap["rev"], 1)
        self.assertEqual(snap["types"]["embedding"][0]["name"], "all-MiniLM")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["schema_version"], 1)

    def test_rejects_bad_input_and_secrets(self):
        store = self.store()
        cases = [
            (("bogus", "p", "", "m"), "invalid_model_type"),
            (("chat", "", "", "m"), "invalid_provider"),
            (("chat", "bad provider", "", "m"), "invalid_provider"),
            (("chat", "p", "", ""), "invalid_name"),
            (("chat", "p", "", "x" * 600), "invalid_name"),
            (("chat", "p", "", "a\nb"), "invalid_name"),
            (("chat", "p", "http://u:pw@h/v1", "m"), "api_base_credentials"),
            (("chat", "p", "http://h/v1?key=1", "m"), "api_base_query"),
            (("chat", "p", "not a url", "m"), "invalid_api_base"),
        ]
        for args, code in cases:
            with self.subTest(args=args):
                with self.assertRaises(FavoritesError) as ctx:
                    store.set_favorite(*args, True)
                self.assertEqual(ctx.exception.code, code)
        self.assertFalse(self.path.exists())

    def test_loaded_junk_is_dropped_not_fatal(self):
        self.path.write_text(json.dumps({"schema_version": 1, "rev": 4, "types": {
            "chat": [
                {"provider": "p", "api_base": "", "name": "ok", "starred_at": 5, "last_used_at": 6},
                {"provider": "p", "api_base": "http://u:pw@h", "name": "leaks", "starred_at": 1},
                {"provider": "p", "api_base": "", "name": "ok"},
                "garbage",
            ],
            "bogus": [{"provider": "p", "name": "x"}],
        }}), encoding="utf-8")
        snap = self.store().snapshot()
        self.assertEqual([i["name"] for i in snap["types"]["chat"]], ["ok"])
        self.assertEqual(snap["rev"], 4)


class StoreRobustness(StoreCase):
    def test_corrupt_file_is_quarantined_and_backup_restored(self):
        store = self.store()
        store.set_favorite("chat", "p", "", "one", True)
        store.set_favorite("chat", "p", "", "two", True)  # second write creates .bak with "one"
        self.path.write_text("{not json", encoding="utf-8")
        snap = self.store().snapshot()
        self.assertEqual([i["name"] for i in snap["types"]["chat"]], ["one"])
        self.assertTrue(list(self.path.parent.glob("favorites.json.corrupt-*")))
        self.store().set_favorite("chat", "p", "", "three", True)  # still writable afterwards
        self.assertEqual(len(self.store().snapshot()["types"]["chat"]), 2)

    def test_corrupt_without_backup_starts_empty(self):
        self.path.write_text("[]", encoding="utf-8")
        self.assertEqual(self.store().snapshot()["types"]["chat"], [])
        self.assertTrue(list(self.path.parent.glob("favorites.json.corrupt-*")))

    def test_stale_lock_is_cleared(self):
        store = self.store(lock_stale=0.05)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        store.lock_path.write_text("", encoding="utf-8")
        old = time.time() - 60
        os.utime(store.lock_path, (old, old))
        store.set_favorite("chat", "p", "", "m", True)
        self.assertFalse(store.lock_path.exists())

    def test_fresh_lock_reports_busy(self):
        store = self.store(lock_timeout=0.1)
        store.lock_path.parent.mkdir(parents=True, exist_ok=True)
        store.lock_path.write_text("", encoding="utf-8")
        with self.assertRaises(FavoritesError) as ctx:
            store.set_favorite("chat", "p", "", "m", True)
        self.assertEqual(ctx.exception.code, "busy")
        self.assertTrue(store.lock_path.exists(), "a lock we did not take must not be removed")

    def test_no_lost_updates_across_threads(self):
        errors = []

        def worker(worker_id):
            try:
                store = store_mod.FavoritesStore(self.path)
                for n in range(12):
                    store.set_favorite("chat", "p", "", f"w{worker_id}-m{n}", True)
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store().snapshot()["types"]["chat"]), 8 * 12)

    def test_two_module_copies_do_not_lose_updates(self):
        """Agent Zero purges plugin modules on plugin events; module-level locks would not span copies."""
        copies = [load_helper("favorites_store") for _ in range(2)]
        errors = []

        def worker(module, tag):
            try:
                store = module.FavoritesStore(self.path)
                for n in range(15):
                    store.set_favorite("utility", "p", "", f"{tag}-{n}", True)
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        threads = [threading.Thread(target=worker, args=(copies[i % 2], f"c{i}")) for i in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store().snapshot()["types"]["utility"]), 4 * 15)

    def test_leftover_temp_files_are_harmless(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        (self.path.parent / ".favorites.json.123.456.tmp").write_text("{", encoding="utf-8")
        store = self.store()
        store.set_favorite("chat", "p", "", "m", True)
        self.assertEqual(len(store.snapshot()["types"]["chat"]), 1)


class Dispatch(StoreCase):
    def handle(self, payload, settings=None):
        return store_mod.handle(payload, self.store(), settings or {"favorites_shown": 5})

    def test_actions(self):
        boot = self.handle({"action": "bootstrap"})
        self.assertTrue(boot["ok"])
        self.assertIn("settings", boot)
        self.assertEqual(set(boot["types"]), {"chat", "vision", "utility", "embedding"})
        self.assertNotIn("settings", self.handle({"action": "list"}))
        self.assertEqual(self.handle({"action": "settings"}), {"ok": True, "settings": {"favorites_shown": 5}})
        res = self.handle({"action": "set", "model_type": "chat", "provider": "p", "api_base": "", "name": "m", "on": True})
        self.assertTrue(res["ok"] and res["starred"])
        self.assertEqual(res["types"]["chat"][0]["name"], "m")
        res = self.handle({"action": "touch", "model_type": "chat", "provider": "p", "api_base": "", "name": "m"})
        self.assertTrue(res["ok"] and res["touched"])

    def test_errors_are_structured(self):
        self.assertEqual(self.handle({"action": "nope"})["error"], "unknown_action")
        self.assertEqual(self.handle({"action": "set", "model_type": "chat", "provider": "p", "name": "m"})["error"], "invalid_request")
        self.assertEqual(self.handle({"action": "set", "model_type": "zzz", "provider": "p", "name": "m", "on": True})["error"], "invalid_model_type")
        self.assertEqual(self.handle(["x"])["error"], "invalid_request")
        default = self.handle({})
        self.assertTrue(default["ok"], "no action means bootstrap")

    def test_storage_failure_is_reported_not_raised(self):
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_text("file, not a directory", encoding="utf-8")
        store = store_mod.FavoritesStore(blocker / "favorites.json")
        result = store_mod.handle({"action": "set", "model_type": "chat", "provider": "p", "api_base": "", "name": "m", "on": True}, store, {})
        self.assertFalse(result["ok"])
        self.assertIn(result["error"], ("storage_error", "busy"))


if __name__ == "__main__":
    unittest.main()
