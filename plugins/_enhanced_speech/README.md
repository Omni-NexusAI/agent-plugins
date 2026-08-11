# Enhanced Speech

Agentspine built-in speech overlay for Agent Zero-compatible runtimes.

## Purpose

`_enhanced_speech` keeps Agentspine speech behavior in a plugin package instead
of relying on dirty core edits. The current implementation focuses on two
runtime behaviors:

- Detecting and exposing a remote Kokoro TTS worker or endpoint.
- Replacing the browser-side STT recorder with a safer speech/silence-driven
  recorder that uses the host's current Whisper transcription route.

The plugin is packaged as an underscore built-in overlay and is expected to load
from `/a0/plugins/_enhanced_speech` in baked Agentspine images. It is not yet a
marketplace/custom-plugin distribution.

## Runtime Design

- `plugin.yaml` keeps the built-in plugin user-toggleable and associates it
  with the agent settings section.
- `extensions/python/startup_migration/_05_enhanced_speech_remote_tts.py`
  installs the Kokoro synthesis adapter early during startup and then applies
  optional remote-worker settings integration.
- `extensions/python/agent_init/_10_enhanced_speech.py` applies the same patch
  for agent runtime initialization and stores `enhanced_speech_loaded` on the
  agent when available. Each adapter is isolated so a missing legacy settings
  API cannot suppress blended Kokoro synthesis.
- `helpers/remote_tts.py` is the single source of truth for remote worker
  detection, default URL handling, and monkey-patching `helpers.settings` plus
  `helpers.build_type`.
- `extensions/webui/initFw_end/enhanced-stt-recorder.js` patches the frontend
  speech store once and replaces `speechStore.initMicrophone`.
- `extensions/webui/page-head/_10_enhanced_speech_legacy_ui.html` owns the
  cross-version Kokoro modal adapter and renders the full `primary + secondary`
  summary in both legacy cards and Spine 9.9's Resolved Config dashboard card.
- `webui/thumbnail.svg` is retained as the catalog icon. A startup adapter
  advertises SVG thumbnails on hosts whose inventory scans raster formats only.

## How It Functions

Remote TTS detection checks explicit settings first, then environment variables,
then the Compose sidecar URL `http://kokoro-worker:8891` when remote TTS is
enabled or the runtime reports a hybrid GPU build. The legacy
`kokoro-gpu-worker` and `agentspine-kokoro-gpu` aliases remain valid for saved
pre-9.9 settings. A configured URL may omit the scheme; the helper normalizes
it to HTTP. Reachability is tested through `/health` with a socket fallback.

When a remote endpoint is available, the helper adds the `remote` TTS device
option, fills `tts_kokoro_remote_url`, enables Kokoro TTS, and moves auto/CPU
device settings to `remote`. The patch is idempotent through
`settings_module._agentspine_enhanced_speech_patched`.

Kokoro settings preserve the host `voice` field as the primary voice and save
the optional secondary voice and primary blend percentage with it. Local
synthesis uses Kokoro's public `load_voice` embeddings and accepts its current
`(graphemes, phonemes, audio)` output tuple, with a guarded older-runtime
fallback; remote synthesis forwards the same three values to the worker. The
Kokoro card displays `primary + secondary`
when a secondary voice is selected. Mirrored provider configuration files are
replaced atomically, so a concurrent status refresh cannot read a partial JSON
file during a settings save. The plugin-owned save route then mirrors the
just-saved normalized contract into `_kokoro_tts` before runtime reads resume;
it does not re-apply stale provider voice or speed values over that save.

Whisper placement is also plugin-local: its settings modal exposes a
Processing device selector, and the default `auto` policy selects CUDA when
the active runtime reports it while explicit CPU policy remains honored. The
selector lists each CUDA device that the current container can use by its
actual runtime name and index (for example, `NVIDIA GeForce RTX 3080 Laptop
GPU (CUDA:0)`). Its chosen `cuda:N` value is atomically persisted through the
plugin-owned STT bridge and used by Whisper; Kokoro has the same device policy.
A device that is no longer reserved by the container resolves to
CPU instead of silently selecting a different accelerator. The adapter
publishes the requested and effective device through the native Whisper runtime
configuration without modifying the host Whisper package.
On compatible hosts whose generic Whisper save path tries to decode a malformed
legacy config, Enhanced Speech handles only the Whisper modal's Save action
through that same atomic bridge and closes the modal after success. This keeps
model, language, message mode, silence, and device settings together without
changing host code or leaving the Save button busy.

Spine 9.9's native Kokoro status response exposes only its primary `voice`.
Some compatible hosts also retain a GET-only Kokoro status handler even though
their public JSON client uses POST. The dashboard therefore hydrates from the
plugin-owned `speech_config` route, which returns both the complete normalized
contract and the authoritative provider toggle state. This keeps an enabled
Kokoro card visible without changing host code or overriding an intentional
plugin disable. The page-head adapter imports the public native `kokoroTts`
store when it was not yet attached to Alpine, then hydrates and registers its
provider before a chat Speak action. This avoids a fresh v2.7/Spine page
silently having no Kokoro playback provider. A companion `initFw_end` bridge
runs after Alpine initialization as the authoritative v2.7/Spine card
hydration point. After a real Save response the card is redrawn through the
host's bounded post-save render window, so the summary updates without
reopening the dashboard.

The config-get extension is deliberately non-recursive: it normalizes the
Kokoro payload already returned by the host rather than re-entering the host
config getter. This keeps status, card hydration, and settings saves responsive
on current Agent Spine builds. The plugin-owned settings bridge likewise reads
and atomically writes only its own and Kokoro's plugin configuration files,
preserving unknown keys and never writing host-core settings files. A successful
plugin-owned save sends one Enhanced Speech notification showing the resolved
voice pair and mode, so voice/mode changes have visible confirmation.

Provider enablement follows the current A0 `.toggle-1`/`.toggle-0` markers in
both the built-in and config-only user roots, while retaining the older
`.enabled`/`.disabled` names as compatibility input. This keeps the Kokoro and
Whisper cards in sync with the host Plugin UI after a user toggle.

The frontend recorder uses `MediaRecorder` plus a Web Audio analyser. It starts
recording when RMS audio exceeds the configured silence threshold, waits for the
configured silence duration, sends base64 audio to the selected transcription
route, filters empty
or structured/noise-only responses, and forwards final text through the normal
chat speech store. Its permission probe immediately releases its temporary
stream before recorder initialization, matching the current Whisper store and
avoiding a second capture request being blocked by browsers with exclusive
microphone access.

The recorder resolves its host binding dynamically. On older compatible hosts
it uses the legacy chat speech and microphone-setting stores; on A0 v2.7 it
uses the public `_whisper_stt` store plus `sttService`. Both paths preserve
device selection, recorder status, send-mode behavior, and safe disposal. If
neither host surface exists, the plugin leaves the native recorder untouched.
On v2.7, Enhanced Speech initializes that public store when the chat toolbar
loads, so microphone dictation is available even if the user has not first
opened Whisper's separate dashboard page.
It also hydrates the store from the plugin-owned `stt_status` route after a
native refresh, so an inconsistent optional host status response cannot make an
enabled Whisper provider appear disabled in the chat toolbar.
It probes the public module asset before importing a version-specific binding,
preferring the current Whisper route so release targets do not request removed
legacy assets; an expected compatibility fallback does not create
browser-console 404s.

## Configuration Surface

Recognized settings keys:

- `tts_kokoro_remote_url`
- `kokoro_remote_url`
- `tts_remote_url`

Recognized environment variables:

- `A0_TTS_KOKORO_REMOTE_URL`
- `A0_SET_TTS_KOKORO_REMOTE_URL`
- `KOKORO_WORKER_URL`
- `KOKORO_GPU_WORKER_URL`
- `A0_TTS_REMOTE_URL`
- `A0_ENABLE_REMOTE_TTS`
- `A0_TTS_REMOTE_WORKER`

## Safe Extension Points

- Add new remote endpoint discovery rules in `helpers/remote_tts.py`.
- Add new settings/env aliases in `_configured_url`.
- Tune recording thresholds through the existing speech store settings instead
  of hard-coding new frontend constants.
- Keep additional frontend recorder patches idempotent by following the
  `_enhancedSpeechRecorderPatched` pattern.

## Compatibility Notes

- The helper imports `helpers.settings` and `helpers.build_type`; changes to
  those core APIs must be reflected here.
- The STT recorder uses `/plugins/_whisper_stt/transcribe` on current v2.7 and
  Spine hosts, falling back to legacy `/transcribe` only on older compatible
  hosts. Both routes accept `{ audio, mime_type }` and return `{ text }`.
- The recorder depends on browser `MediaRecorder`, `AudioContext`, and
  `navigator.mediaDevices`.
- On the current Spine parent image, the host WebUI requests the absent legacy
  asset `/components/chat/speech/speech-store.js` and emits a 404 in the
  browser console. This is a host-side asset issue outside this plugin; the
  automated Kokoro save, card, and synthesis checks complete without Enhanced
  Speech console errors.
- The current A0 v1.2 and v2.7 validation images contain the native
  `_kokoro_tts` runtime files, but their Plugin-page catalog does not surface
  that provider in either tab. The custom Enhanced Speech plugin and its
  backend synthesis adapter are discoverable; browser automation of the
  host-owned Kokoro modal remains blocked until those hosts expose the provider
  catalog entry again.
- The locally available legacy `v0.9.9-gpu-pre-local` parent exposes CUDA but
  has no `plugins/_kokoro_tts` runtime to adapt (only an older helper module).
  Enhanced Speech intentionally remains inert there; do not promote that image
  as a full-GPU Enhanced Speech release. The validated GPU path is the current
  RC with its separate CUDA Kokoro worker.

## Verification Checklist

- Compile the plugin Python files.
- Confirm `get_tts_device_options()` includes `remote` when a configured or
  reachable worker exists.
- Confirm `get_settings()` fills `tts_kokoro_remote_url` and selects `remote`
  when appropriate.
- Open the chat UI, grant microphone access, speak, pause, and confirm the text
  is submitted through the normal speech flow.
- Confirm repeated agent initialization does not double-patch settings or the
  frontend speech store.
- Browser-save a primary voice, secondary voice, blend, and speed; wait for
  the plugin-owned save response; then verify persistence and the visible
  `primary + secondary` card summary before restoring test values.
- Browser-save the Whisper Processing device selection, reopen the modal, and
  verify the saved `auto`, `cpu`, or actual `cuda:N` value is retained.
