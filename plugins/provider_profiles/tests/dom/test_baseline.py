"""Baseline: the harness reproduces official model-field behaviour on both pinned hosts."""
from __future__ import annotations

import unittest

from .base import DomCase


class BaselineMixin:
    def test_official_dropdown_opens_and_selects(self):
        page = self.open_harness()
        field = "#slot-chat input[x-model='model.name']"
        page.fill(field, "")
        page.click(field)
        page.wait_for_selector("#slot-chat .model-search-results .model-search-item:not(.disabled)")
        rows = page.locator("#slot-chat .model-search-results .model-search-item:not(.disabled)").all_inner_texts()
        self.assertEqual(rows, sorted(self.server.state.models["openrouter"], key=str.lower))
        page.click("#slot-chat .model-search-item:has-text('meta/llama-3')")
        self.assertEqual(page.input_value(field), "meta/llama-3")
        self.assertEqual(self.errors(), [])

    def test_official_search_filters_by_field_text(self):
        # Documents the official quirk the plugin works around: a filled field lists only near-matches.
        page = self.open_harness()
        field = "#slot-chat input[x-model='model.name']"
        page.click(field)  # field holds deepseek/deepseek-v4
        page.wait_for_selector("#slot-chat .model-search-results .model-search-item:not(.disabled)")
        rows = page.locator("#slot-chat .model-search-results .model-search-item:not(.disabled)").all_inner_texts()
        self.assertEqual(rows, ["deepseek/deepseek-v4"])
        body = self.server.state.calls("/model_search")[-1]["body"]
        self.assertEqual(body["query"], "deepseek/deepseek-v4")
        self.assertEqual(body["model_type"], "chat")


class BaselineV211(BaselineMixin, DomCase):
    host = "v2.11"


class BaselineV214(BaselineMixin, DomCase):
    host = "v2.14"

    def test_save_rebuilds_kwargs_from_text(self):
        # v2.14 savePresets() drops kwargs that are not mirrored in _kwargs_text.
        page = self.open_harness()
        page.evaluate("""() => { const d = Alpine.$data(document.querySelector('#editor')); d.selectedPreset.chat.kwargs = {a: 1}; d.selectedPreset.chat._kwargs_text = ''; }""")
        page.click("#btn-save")
        saved = page.evaluate("window.__saved[0].chat.kwargs")
        self.assertEqual(saved, {})


if __name__ == "__main__":
    unittest.main()
