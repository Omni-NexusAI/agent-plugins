# Enhanced Speech DOX

## Purpose

`_enhanced_speech` owns Agentspine speech extensions that should survive A0 core
updates as a built-in plugin overlay.

## Ownership

- `helpers/remote_tts.py` owns remote Kokoro endpoint detection, TTS defaults,
  and settings/build-type monkey patches.
- `extensions/python/startup_migration/_05_enhanced_speech_remote_tts.py`
  applies the remote TTS patch during startup.
- `extensions/python/agent_init/_10_enhanced_speech.py` applies the same patch
  during agent initialization and marks the agent as loaded.
- `helpers/kokoro_adapter.py` owns local embedding mixing and remote forwarding
  of primary voice, secondary voice, blend, speed, and mode.
- `helpers/config.py` owns the normalized speech contract and atomic mirrored
  provider-config replacement. It resolves config assets directly rather than
  calling the host config getter, because current Kokoro/Whisper hooks invoke
  their runtime normalizers and would otherwise recurse through this adapter.
- `api/speech_config.py` owns the browser-safe Kokoro configuration and toggle
  bridge. It must use the public plugin toggle, rather than assuming the
  host-native status route accepts the WebUI JSON client's POST requests.
  Read and atomically update only plugin-local config files there; never
  re-enter the host config getter from that API handler.
- `api/stt_status.py` owns the equivalent toggle/config bridge for the public
  Whisper store. It must report plugin discovery and toggle state without
  depending on the optional host Whisper status handler.
- `api/stt_config.py` owns atomic persistence of normalized Whisper settings.
  It mirrors only `_enhanced_speech` and `_whisper_stt` plugin config files so
  a selected STT processing device survives a native modal save without
    writing host-core files.
- The Kokoro and Whisper status/save bridges must respect current host
  `.toggle-1`/`.toggle-0` markers in built-in and config-only user roots;
  `.enabled`/`.disabled` remain legacy compatibility input only.
- The speech and STT API bridges must derive the real A0 runtime root from the
  enclosing `plugins` and `usr` directories. They are deployed both as Spine
  built-ins (`/a0/plugins`) and as A0 custom packages (`/a0/usr/plugins`), so
  a fixed source-path depth would address the wrong provider/config roots.
- The `_get_config` extension runs inside the host config getter. It may
  normalize the returned Kokoro provider payload, but must never call back
  into `get_plugin_config` or aggregate configuration helpers from that hook.
- `extensions/webui/initFw_end/enhanced-stt-recorder.js` owns the frontend
  recorder replacement and post-Alpine Kokoro card hydration for current
  A0/Spine stores.
- `extensions/webui/page-head/_10_enhanced_speech_legacy_ui.html` owns
  compatibility modal persistence and the legacy/Spine 9.9 Kokoro card
  summaries, including the host's bounded post-save redraw window.
- `extensions/python/startup_migration/_06_enhanced_speech_svg_plugin_thumbnails.py`
  owns the plugin-local catalog adapter for hosts that serve SVG thumbnails but
  only advertise raster thumbnail formats.

## Local Contracts

- Keep remote TTS detection centralized in `helpers/remote_tts.py`.
- Persist mirrored Kokoro provider settings through an atomic replacement; status
  refreshes may run concurrently with a settings save and must never see an
  empty JSON document.
- When the plugin-owned save route mirrors settings into `_kokoro_tts`, use the
  just-saved Enhanced Speech contract as authoritative. Normal runtime reads
  may give the provider file precedence, but must never write stale primary
  voice or speed values back over that save.
- Treat `voice`, `primary_voice`, `secondary_voice`, and `voice_blend` as one
  normalized contract so the displayed voice summary matches synthesis.
- Prefer Kokoro's public `load_voice` and documented
  `(graphemes, phonemes, audio)` synthesis tuple; retain a guarded
  `load_single_voice` fallback only for older compatible host runtimes.
- `helpers/whisper_adapter.py` owns explicit Whisper `auto`/`cuda`/`cpu`
  placement. It must patch the host runtime rather than copy or edit
  `_whisper_stt`, and its status-facing effective device must agree with the
  actual model-load device.
- `helpers/gpu.py` owns runtime CUDA inventory and selected-device resolution.
  It must list only accelerator devices usable by the current container, retain
  a saved `cuda:N` selection, and never infer GPU access from an image name.
- Keep the injected remote-timeout control explicitly scoped. The host speed
  field can be moved into the same group and must never be mistaken for the
  remote request timeout during a save.
- Install `kokoro_adapter.patch_runtime()` during both startup migration and
  agent initialization; remote-TTS settings integration is optional and must
  not prevent the synthesis adapter from loading.
- Resolve the recorder through the legacy speech store when present or A0
  v2.7's public `_whisper_stt`/`sttService` surface when it is not. The v2.7
  adapter must initialize the public Whisper store when the chat toolbar loads
  (its separate dashboard may never be opened), and preserve selected-device
  handling, status notifications, send-mode behavior, and `stop()`/`dispose()`
  compatibility.
- The page-head v2.7 status bridge rehydrates that store after every native
  refresh so a stale/unsupported native status response cannot unregister an
  enabled recorder provider. Both the recorder and bridge must retry a
  temporarily unavailable public module for a short bounded window during
  fresh CUDA startup, then remain inert on hosts that genuinely lack that
  surface.
- The permission probe must release every temporary `getUserMedia` track before
  Enhanced Speech opens its recorder stream; permission or device failures must
  be visible through the host notification/toast surface.
- Probe public recorder-module assets before importing a version-specific
  binding. Prefer the v2.7 Whisper route on current targets; an unavailable
  legacy path is an expected compatibility condition, not a browser-console
  404.
- Preserve explicit settings/env values before probing default sidecars.
- Prefer the Compose-owned `kokoro-worker:8891` endpoint. Retain legacy worker
  aliases in the plugin's probe list so a sidecar can attach to an existing
  standard build on the same Compose network without rewriting saved settings.
- Keep patch guards idempotent:
  `settings_module._agentspine_enhanced_speech_patched` and
  `speechStore._enhancedSpeechRecorderPatched`.
- The page-head adapter may load before native Kokoro registers its public
  `kokoroTts` Alpine store. It must also import the public v2.7 store module,
  hydrate it, and register its provider before a Speak action; do not infer
  enablement from DOM state.
- The Whisper modal's processing-device selector must use the same runtime
  CUDA inventory as Kokoro, persist `auto`/`cpu`/`cuda:N` through
  `api/stt_config.py`, and hide CUDA choices when the container has no usable
  CUDA reservation. On hosts whose generic Whisper `save_config` route can
  hang while decoding a legacy config, intercept only that modal's Save action,
  atomically persist the full supported STT contract through the plugin route,
  then close the modal; never patch host source or intercept another plugin's
  save action.
- Retain `webui/thumbnail.svg`; the catalog adapter advertises it only when the
  host omitted a thumbnail URL, so no host inventory code needs modification.
- The recorder uses `/plugins/_whisper_stt/transcribe` when the public v2.7
  Whisper store is present and the legacy `/transcribe` route only on older
  hosts. Keep the shared `{ audio, mime_type }` contract and update this
  plugin and README together if either route changes.

## Work Guidance

- Add new endpoint aliases to `_configured_url`.
- Add new device-option behavior through `ensure_remote_tts_option`.
- Tune frontend recording behavior through existing speech store settings when
  possible.
- Keep browser recorder errors visible through existing toast/error helpers.

## Verification

- Parse touched Python files.
- Confirm remote TTS settings are filled only when a configured or reachable
  endpoint exists.
- Confirm the frontend recorder initializes once and can submit transcribed text.
- Browser-save a two-voice configuration and confirm the same dashboard card
  redraws as `primary + secondary` after the plugin-owned save response.
- Browser-save a mode/voice change and confirm one Enhanced Speech notification
  identifies the resolved voice pair and runtime device label.
- Browser-save a Whisper processing-device choice and confirm it reports the
  effective device, persists after reopening, and the adapter loads Whisper on
  that same device.
- A CUDA-capable parent still needs the native `_kokoro_tts` plugin runtime for
  this adapter. Treat legacy GPU images without that provider as unsupported
  and record the limitation instead of adding host-core fallbacks.

## Child DOX Index

This plugin has no child DOX files.
