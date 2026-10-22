"""Shared Playwright plumbing for the DOM harness tests (skipped when unavailable)."""
from __future__ import annotations

import tempfile
import unittest
from urllib.parse import urlencode

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

from .server import HarnessServer

HOSTS = ("v2.11", "v2.14")


def launch(playwright):
    last = None
    for kwargs in ({}, {"channel": "chrome"}):
        try:
            return playwright.chromium.launch(headless=True, **kwargs)
        except Exception as error:  # noqa: BLE001
            last = error
    raise unittest.SkipTest(f"no usable Chromium for Playwright: {last}")


class DomCase(unittest.TestCase):
    """One browser per class; a fresh server+page per test via open_harness()."""

    host = "v2.14"

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        cls._pw = sync_playwright().start()
        cls.browser = launch(cls._pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()

    FAVORITES_EXT = "_10_provider_profiles.html,_20_model_favorites.html"

    def open_harness(self, *, ext="", order="ext-first", setup=None, favorites=None, params=None, init_script=None, discovery=None):
        """favorites: None = no favorites service; dict = settings overrides for the real store-backed service.
        discovery: None = no discover_models service (404); dict = kwargs of HarnessState.enable_discovery()."""
        server = HarnessServer(self.host)
        if favorites is not None:
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            server.state.enable_favorites(tmp.name, favorites)
        if discovery is not None:
            server.state.enable_discovery(**discovery)
        if setup:
            setup(server.state)
        server.start()
        self.addCleanup(server.stop)
        self.server = server
        context = self.browser.new_context(viewport={"width": 900, "height": 900})
        self.addCleanup(context.close)
        if init_script:
            context.add_init_script(init_script)
        page = context.new_page()
        self.page = page
        query = urlencode({"host": self.host, "ext": ext, "order": order, **(params or {})})
        page.goto(f"{server.url}/harness.html?{query}")
        page.wait_for_function("window.__ready === true", timeout=15000)
        return page

    def errors(self):
        return self.page.evaluate("window.__errors")
