"""Favorites UI on the real upstream model field + store (pinned v2.11 and v2.14)."""
from __future__ import annotations

import unittest

from .base import DomCase

CHAT_INPUT = "#slot-chat input[x-model='model.name']"
CHAT_ROWS = "#slot-chat .model-search-results .model-search-item:not(.disabled)"
CHAT_CARD = "#slot-chat .pp-card:not([hidden])"
EDITOR = "Alpine.$data(document.querySelector('#editor'))"


def seed(*entries):
    """entries: (type, provider, api_base, name); applied before the page loads."""
    def setup(state):
        for entry in entries:
            state.favorites_store.set_favorite(*entry, True)
    return setup


class FavoritesUiMixin:
    def open_fav(self, *, favorites=None, entries=(), setup=None, **kw):
        seeder = seed(*entries)

        def both(state):
            seeder(state)
            if setup:
                setup(state)

        page = self.open_harness(ext=self.FAVORITES_EXT, favorites={} if favorites is None else favorites, setup=both, **kw)
        page.wait_for_selector("#slot-chat .pp-star-input", timeout=15000)
        return page

    def core_rows(self, slot="chat"):
        return self.page.evaluate(
            "(slot) => [...document.querySelectorAll(`#slot-${slot} .model-search-results .model-search-item:not(.disabled)`)].map(r => Alpine.$data(r).m)", slot)

    def card_names(self, slot="chat"):
        return self.page.evaluate(
            "(slot) => [...document.querySelectorAll(`#slot-${slot} .pp-card .pp-card-name`)].map(n => n.textContent)", slot)

    def stored(self, model_type="chat"):
        return [(e["provider"], e["api_base"], e["name"]) for e in self.server.state.favorites_store.snapshot()["types"][model_type]]

    def wait_stored(self, expected, model_type="chat", timeout_ms=5000):
        """The star flips optimistically; wait until the server file reflects it."""
        waited = 0
        while waited < timeout_ms:
            if self.stored(model_type) == expected:
                return
            self.page.wait_for_timeout(50)
            waited += 50
        self.assertEqual(self.stored(model_type), expected)

    def model(self, slot="chat"):
        return self.page.evaluate(f"() => ({EDITOR}).selectedPreset.{slot}")

    # ---------------------------------------------------------------- stars
    def test_stars_on_rows_and_input_persist_server_side(self):
        page = self.open_fav()
        page.fill(CHAT_INPUT, "")
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_ROWS)
        page.click("#slot-chat .model-search-item:has-text('meta/llama-3') .pp-star")
        page.wait_for_function("document.querySelector('#slot-chat .model-search-item .pp-star-on') !== null")
        self.wait_stored([("openrouter", "", "meta/llama-3")])
        self.assertEqual(page.input_value(CHAT_INPUT), "", "starring must not select the row")
        page.reload()
        page.wait_for_function("window.__ready === true")
        page.wait_for_selector("#slot-chat .pp-star-input")
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_ROWS)
        self.assertEqual(page.locator("#slot-chat .model-search-item:has-text('meta/llama-3') .pp-star").inner_text(), "★")
        self.assertEqual(self.errors(), [])

    def test_manual_entry_can_be_favorited_and_unfavorited(self):
        page = self.open_fav()
        page.fill(CHAT_INPUT, "my-custom-model")
        page.click("#slot-chat .pp-star-input")
        page.wait_for_function("document.querySelector('#slot-chat .pp-star-input').classList.contains('pp-star-on')")
        self.wait_stored([("openrouter", "", "my-custom-model")])
        page.click("#slot-chat .pp-star-input")
        page.wait_for_function("!document.querySelector('#slot-chat .pp-star-input').classList.contains('pp-star-on')")
        self.wait_stored([])

    def test_utility_slot_uses_the_effective_provider(self):
        page = self.open_fav()
        page.click("#slot-utility input[x-model='model.name']")
        page.wait_for_selector("#slot-utility .model-search-results .model-search-item:not(.disabled)")
        page.click("#slot-utility .model-search-item:has-text('meta/llama-3') .pp-star")
        page.wait_for_function("document.querySelector('#slot-utility .model-search-item .pp-star-on') !== null")
        self.wait_stored([("openrouter", "", "meta/llama-3")], "utility")
        self.assertEqual(self.stored("chat"), [])

    # ---------------------------------------------------------------- card
    def test_card_opens_instantly_while_the_endpoint_hangs(self):
        page = self.open_fav(entries=[("chat", "openrouter", "", "deepseek/deepseek-v4")], setup=lambda s: setattr(s, "search_mode", "hang"))
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_CARD, timeout=1500)
        self.assertEqual(self.card_names(), ["deepseek/deepseek-v4"])
        self.assertEqual(self.core_rows(), [])
        self.server.state.release.set()
        page.wait_for_selector(CHAT_ROWS)
        card = page.locator("#slot-chat .pp-card").bounding_box()
        results = page.locator("#slot-chat .model-search-results").first.bounding_box()
        self.assertLessEqual(card["y"] + card["height"], results["y"] + 1, "results box must sit below the favorites card")
        self.assertEqual(self.errors(), [])

    def test_card_pins_five_most_recent_and_show_all(self):
        entries = [("chat", "openrouter", "", f"model-{i}") for i in range(7)]
        page = self.open_fav(entries=entries)
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_CARD)
        self.assertEqual(self.card_names(), ["model-6", "model-5", "model-4", "model-3", "model-2"])
        page.click("#slot-chat .pp-card-more")
        self.assertEqual(len(self.card_names()), 7)
        self.assertEqual(page.locator("#slot-chat .pp-card-more").inner_text(), "Show fewer")

    def test_card_hidden_without_favorites_for_this_type(self):
        page = self.open_fav(entries=[("utility", "openrouter", "", "only-utility")])
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_ROWS)
        self.assertEqual(page.locator("#slot-chat .pp-card:not([hidden])").count(), 0)

    def test_favorites_stay_pinned_while_typing_and_results_narrow(self):
        entries = [("chat", "openrouter", "", n) for n in ("alpha-1", "beta-2", "gamma-3", "qwen/qwen3-30b")]
        page = self.open_fav(entries=entries)
        page.fill(CHAT_INPUT, "")
        page.click(CHAT_INPUT)
        page.keyboard.type("qwen", delay=25)
        page.wait_for_function("document.querySelectorAll('#slot-chat .model-search-results .model-search-item:not(.disabled)').length === 1", timeout=5000)
        self.assertEqual(self.core_rows(), ["qwen/qwen3-30b"])
        names = self.card_names()
        self.assertEqual(names[0], "qwen/qwen3-30b", "matching favorite first")
        self.assertEqual(sorted(names), sorted(["alpha-1", "beta-2", "gamma-3", "qwen/qwen3-30b"]), "all favorites stay pinned")
        queries = [c["body"]["query"] for c in self.server.state.calls("/model_search")]
        self.assertEqual(set(queries), {""}, "the plugin asks the host for the full list and narrows locally")
        self.assertEqual(page.locator("#slot-chat .model-search-item .pp-star").count(), 1, "stars survive the regroup")

    def test_opening_a_filled_field_shows_everything_matches_first(self):
        page = self.open_fav()
        page.click(CHAT_INPUT)  # field holds deepseek/deepseek-v4
        page.wait_for_selector(CHAT_ROWS)
        rows = self.core_rows()
        self.assertEqual(rows[0], "deepseek/deepseek-v4")
        self.assertEqual(sorted(rows), sorted(self.server.state.models["openrouter"]))
        self.assertEqual(self.server.state.calls("/model_search")[-1]["body"]["query"], "")

    def test_search_results_are_cached_briefly(self):
        page = self.open_fav()
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_ROWS)
        page.mouse.click(5, 5)  # outside: closes
        page.wait_for_function("document.querySelectorAll('#slot-chat .model-search-results .model-search-item').length >= 0")
        page.click(CHAT_INPUT)
        page.wait_for_timeout(300)
        self.assertEqual(len(self.server.state.calls("/model_search")), 1)

    # ---------------------------------------------------------------- applying a favorite
    def test_choosing_a_cross_provider_favorite_fills_provider_base_and_name(self):
        page = self.open_fav(entries=[("chat", "lm_studio", "http://host.docker.internal:1234/v1", "qwen3-30b-a3b")])
        page.evaluate(f"() => {{ const m = ({EDITOR}).selectedPreset.chat; m.name = 'keep-me'; m.kwargs = {{a: 1}}; m._kwargs_text = 'a=1'; }}")
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_CARD)
        page.click("#slot-chat .pp-card-row")
        page.wait_for_function(f"() => ({EDITOR}).selectedPreset.chat.name === 'qwen3-30b-a3b'", timeout=5000)
        model = self.model()
        self.assertEqual((model["provider"], model["api_base"], model["name"]), ("lm_studio", "http://host.docker.internal:1234/v1", "qwen3-30b-a3b"))
        self.assertEqual(page.eval_on_selector("#slot-chat select[x-model='model.provider']", "e => e.value"), "lm_studio")
        self.assertEqual(page.locator(CHAT_CARD).count(), 0, "card closes after choosing")
        profiles = self.server.state.configs.get("_provider_profiles", {}).get("profiles", {})
        self.assertEqual(profiles["chat_model:openrouter"]["name"], "keep-me", "previous provider's selection was remembered")
        page.wait_for_timeout(300)
        touches = [c for c in self.server.state.calls("/favorites") if c["body"].get("action") == "touch"]
        self.assertEqual(len(touches), 1)
        self.assertEqual(self.errors(), [])

    def test_choosing_a_same_provider_favorite_keeps_the_empty_base(self):
        page = self.open_fav(entries=[("chat", "openrouter", "", "meta/llama-3")])
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_CARD)
        page.click("#slot-chat .pp-card-row")
        page.wait_for_function(f"() => ({EDITOR}).selectedPreset.chat.name === 'meta/llama-3'")
        self.assertEqual(self.model()["api_base"], "")
        self.assertEqual(page.input_value(CHAT_INPUT), "meta/llama-3")

    def test_favorite_with_unavailable_provider_is_refused_with_a_message(self):
        page = self.open_fav(entries=[("chat", "strata_router", "https://host.docker.internal:8096/v1", "alias-vision-160k")])
        before = self.model()
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_CARD)
        page.click("#slot-chat .pp-card-row")
        page.wait_for_function("window.__toasts.length > 0", timeout=5000)
        self.assertIn("not available", page.evaluate("window.__toasts[0].message"))
        self.assertEqual(self.model()["name"], before["name"])
        self.assertEqual(self.model()["provider"], before["provider"])

    def test_apply_targets_the_active_preset_after_a_preset_switch(self):
        page = self.open_fav(entries=[("chat", "openrouter", "", "meta/llama-3")])
        page.select_option("#preset-switch", "1")
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_CARD)
        page.click("#slot-chat .pp-card-row")
        page.wait_for_function(f"() => ({EDITOR}).presets[1].chat.name === 'meta/llama-3'")
        self.assertEqual(page.evaluate(f"() => ({EDITOR}).presets[0].chat.name"), "deepseek/deepseek-v4")

    def test_favorites_shown_setting_controls_the_card_size(self):
        entries = [("chat", "openrouter", "", f"m{i}") for i in range(4)]
        page = self.open_fav(favorites={"favorites_shown": 2}, entries=entries)
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_CARD)
        self.assertEqual(self.card_names(), ["m3", "m2"])
        self.assertEqual(page.locator("#slot-chat .pp-card-more").inner_text(), "Show all 4")

    def test_detached_fields_are_pruned(self):
        page = self.open_fav()
        self.assertEqual(page.evaluate("window.__providerProfilesFavorites.fieldCount()"), 3)
        page.evaluate("() => { document.querySelector('#slot-utility').remove(); document.querySelector('#slot-embedding').remove(); }")
        page.fill(CHAT_INPUT, "my-custom-model")
        page.click("#slot-chat .pp-star-input")
        page.wait_for_function("window.__providerProfilesFavorites.fieldCount() === 1", timeout=5000)

    def test_failed_write_reloads_the_servers_truth(self):
        page = self.open_fav(entries=[("chat", "openrouter", "", "keep-1")])
        page.fill(CHAT_INPUT, "will-fail")
        self.server.state.favorites_store.max_per_type = 1  # the next star is refused by the server
        page.click("#slot-chat .pp-star-input")
        page.wait_for_function("window.__toasts.length > 0", timeout=5000)
        page.wait_for_function("!document.querySelector('#slot-chat .pp-star-input').classList.contains('pp-star-on')")
        self.assertEqual(self.stored(), [("openrouter", "", "keep-1")])

    def test_card_stays_open_when_the_host_swaps_from_no_results_to_results(self):
        # Regression found on a live instance: the host hides "No models found" before it shows the results.
        page = self.open_fav(favorites={"normal_results_mode": "core"}, entries=[("chat", "openrouter", "", "meta/llama-3")])
        page.fill(CHAT_INPUT, "")
        page.click(CHAT_INPUT)
        page.keyboard.type("zzzz", delay=20)
        page.wait_for_function("document.querySelector('#slot-chat .model-search-results:nth-of-type(2)') !== null", timeout=3000)
        page.wait_for_timeout(700)
        page.fill(CHAT_INPUT, "qwen")
        page.wait_for_selector(CHAT_ROWS, timeout=5000)
        page.wait_for_timeout(800)
        self.assertEqual(page.locator(CHAT_CARD).count(), 1, "card must survive the host's result swap")

    def test_card_closes_after_the_host_dropdown_really_closes(self):
        page = self.open_fav(entries=[("chat", "openrouter", "", "meta/llama-3")])
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_ROWS)
        page.mouse.click(5, 5)
        page.wait_for_selector(CHAT_CARD, state="detached", timeout=3000)

    def test_card_rows_work_from_the_keyboard(self):
        page = self.open_fav(entries=[("chat", "openrouter", "", "meta/llama-3")])
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_CARD)
        page.focus("#slot-chat .pp-card-row")
        page.keyboard.press("Enter")
        page.wait_for_function(f"() => ({EDITOR}).selectedPreset.chat.name === 'meta/llama-3'")
        self.assertEqual(page.locator(CHAT_CARD).count(), 0)

    def test_long_names_do_not_run_under_the_stars(self):
        page = self.open_fav()
        padding = page.eval_on_selector(CHAT_INPUT, "e => getComputedStyle(e).paddingRight")
        self.assertEqual(padding, "62px", "the host's inline padding-right must be overridden")

    # ---------------------------------------------------------------- lifecycle and safety
    def test_vision_slot_rebuild_reattaches(self):
        page = self.open_fav()
        for _ in range(2):
            page.evaluate(f"() => {{ ({EDITOR}).selectedPreset.chat.vision = false; }}")
            page.wait_for_selector("#slot-vision .pp-star-input", timeout=8000)
            self.assertEqual(page.locator("#slot-vision .pp-star-input").count(), 1)
            page.evaluate(f"() => {{ ({EDITOR}).selectedPreset.chat.vision = true; }}")
            page.wait_for_selector("#slot-vision", state="detached")
        self.assertEqual(self.errors(), [])

    def test_loading_the_extension_twice_is_idempotent(self):
        page = self.open_fav()
        page.evaluate("() => { window.__first = window.__providerProfilesFavorites; }")
        page.evaluate("""() => { const el = document.createElement('x-component'); el.setAttribute('path', '/plugins/provider_profiles/extensions/webui/page-head/_20_model_favorites.html'); document.head.appendChild(el); }""")
        page.wait_for_timeout(500)
        self.assertTrue(page.evaluate("window.__providerProfilesFavorites === window.__first"))
        for slot in ("chat", "utility", "embedding"):
            self.assertEqual(page.locator(f"#slot-{slot} .pp-star-input").count(), 1)

    def test_dispose_removes_everything_and_restores_the_host(self):
        page = self.open_fav()
        page.evaluate("() => window.__providerProfilesFavorites.dispose()")
        self.assertEqual(page.locator(".pp-star, .pp-card").count(), 0)
        self.assertEqual(page.locator(".pp-has-star, .pp-open").count(), 0)
        self.assertEqual(page.evaluate("typeof Alpine.store('modelConfig').providerProfilesTyping"), "undefined")
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_ROWS)
        self.assertEqual(self.server.state.calls("/model_search")[-1]["body"]["query"], "deepseek/deepseek-v4", "host behaviour restored")

    def test_service_down_leaves_the_host_dropdown_untouched(self):
        page = self.open_harness(ext=self.FAVORITES_EXT, favorites={}, setup=lambda s: setattr(s, "favorites_status", 500))
        page.wait_for_timeout(800)
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_ROWS)
        self.assertEqual(page.locator(".pp-star, .pp-card").count(), 0)
        self.assertEqual(self.errors(), [])

    def test_kill_switch(self):
        page = self.open_harness(ext=self.FAVORITES_EXT, favorites={}, init_script="localStorage.setItem('pp_favorites_ui', 'off')")
        page.wait_for_timeout(800)
        self.assertEqual(page.locator(".pp-star, .pp-card").count(), 0)
        self.assertEqual(page.evaluate("typeof window.__providerProfilesFavorites"), "undefined")

    def test_yields_when_the_host_ships_its_own_favorites(self):
        page = self.open_harness(ext=self.FAVORITES_EXT, favorites={}, params={"hostFavorites": "1"})
        page.wait_for_timeout(1000)
        self.assertEqual(page.locator(".pp-star, .pp-card").count(), 0)
        self.assertEqual(page.evaluate("typeof window.__providerProfilesFavorites"), "undefined")

    # ---------------------------------------------------------------- flags-off parity
    def test_flags_off_requests_match_official_behaviour(self):
        page = self.open_harness(ext=self.FAVORITES_EXT, favorites={"favorites_ui": "off", "normal_results_mode": "core"})
        page.wait_for_timeout(600)
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_ROWS)
        self.assertEqual(page.locator(".pp-star, .pp-card").count(), 0)
        self.assertEqual(self.core_rows(), ["deepseek/deepseek-v4"])
        self.assertEqual(self.server.state.calls("/model_search")[-1]["body"]["query"], "deepseek/deepseek-v4")

    def test_core_results_mode_keeps_official_requests_but_still_shows_favorites(self):
        page = self.open_fav(favorites={"normal_results_mode": "core"}, entries=[("chat", "openrouter", "", "meta/llama-3")])
        page.click(CHAT_INPUT)
        page.wait_for_selector(CHAT_ROWS)
        self.assertEqual(self.server.state.calls("/model_search")[-1]["body"]["query"], "deepseek/deepseek-v4")
        self.assertEqual(self.core_rows(), ["deepseek/deepseek-v4"])
        self.assertEqual(self.card_names(), ["meta/llama-3"])


class FavoritesUiV211(FavoritesUiMixin, DomCase):
    host = "v2.11"


class FavoritesUiV214(FavoritesUiMixin, DomCase):
    host = "v2.14"


if __name__ == "__main__":
    unittest.main()
