import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, folder="helpers"):
    spec = importlib.util.spec_from_file_location("speech_test_" + name, ROOT / folder / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def config(monkeypatch):
    module = load("config")
    monkeypatch.setattr(module, "_plugin_config", lambda name: {})
    return module


def test_native_weights_win_over_all_legacy_aliases(config):
    cfg = config.normalize_kokoro_config({"voice": "af_heart", "voice_weights": {"bm_george": 2, "af_nova": 7},
        "primary_voice": "am_adam", "secondary_voice": "am_echo", "voice_blend": 90, "tts_kokoro_voice": "am_santa",
        "custom": {"keep": True}, "device": "cpu", "speed": 1.3})
    assert cfg["voice"] == "bm_george,af_nova"
    assert cfg["voice_weights"] == {"bm_george": 2, "af_nova": 7}
    assert cfg["custom"] == {"keep": True}
    assert cfg["speed"] == 1.3 and cfg["device"] == "cpu"
    assert config.normalize_kokoro_config(cfg) == cfg


def test_equal_weights_and_single_selection_do_not_revive_pair(config):
    for voice in ("af_nova", "af_nova,bm_george"):
        cfg = config.normalize_kokoro_config({"voice": voice, "voice_weights": {}, "secondary_voice": "am_echo", "voice_blend": 90})
        assert cfg["voice"] == voice and cfg["voice_weights"] == {}


def test_legacy_pair_migrates_once(config):
    cfg = config.normalize_kokoro_config({"voice": "af_nova", "secondary_voice": "bm_george", "voice_blend": 30})
    assert cfg["voice_weights"] == {"af_nova": 3, "bm_george": 7}
    assert config.normalize_kokoro_config(cfg) == cfg
    assert config.normalize_kokoro_config({**cfg, "voice": "af_heart", "voice_weights": {}})["voice"] == "af_heart"


def test_weight_maps_replace_instead_of_merging(config):
    for weights in ({}, {"af_heart": 4}):
        cfg = config._deep_merge({"voice_weights": {"am_echo": 8}}, {"voice_weights": weights})
        assert cfg["voice_weights"] == weights


def test_legacy_provider_save_replaces_previously_migrated_weights(config, monkeypatch):
    monkeypatch.setattr(config, "_plugin_config", lambda name: {
        "tts": {"kokoro": {"voice": "af_heart,am_echo", "voice_weights": {"af_heart": 8, "am_echo": 2}, "custom": "keep"}}})
    saved = []
    monkeypatch.setattr(config, "_write_plugin_config", lambda name, value: saved.append(value))
    config.sync_enhanced_from_provider(config.KOKORO_PLUGIN,
        {"voice": "af_nova", "secondary_voice": "bm_george", "voice_blend": 30})
    assert saved[0]["tts"]["kokoro"]["voice_weights"] == {"af_nova": 3, "bm_george": 7}
    assert saved[0]["tts"]["kokoro"]["custom"] == "keep"


def test_invalid_weights_are_discarded(config):
    cfg = config.normalize_kokoro_config({"voice": "af_nova", "voice_weights": {"af_nova": 2, "bm_george": float("nan"), "bad": 3, "am_echo": -1}})
    assert cfg["voice_weights"] == {"af_nova": 2}


def test_atomic_save_reopen_preserves_unknown_and_weights(config, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_config_path", lambda name: tmp_path / (name + ".json"))
    payload = config.provider_kokoro_config({"voice_weights": {"af_nova": 2, "bm_george": 7}, "unrelated": 42})
    config._write_plugin_config("test", payload)
    import json
    reopened = json.loads((tmp_path / "test.json").read_text())
    assert reopened["voice_weights"] == payload["voice_weights"] and reopened["unrelated"] == 42
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("weights,voice,expected", [
    ({"af_nova": 3, "bm_george": 7}, "ignored", ("af_nova", "bm_george", 30)),
    ({}, "af_nova,bm_george", ("af_nova", "bm_george", 50)),
    ({}, "af_nova", ("af_nova", "", 100)),
])
def test_remote_pair_translation(weights, voice, expected):
    actual = load("kokoro_adapter").remote_voice_pair({"voice": voice, "voice_weights": weights})
    assert actual[:2] == expected[:2]
    assert actual[2] == pytest.approx(expected[2])


def test_remote_three_voices_rejected_before_request():
    with pytest.raises(ValueError, match="one or two voices"):
        load("kokoro_adapter").remote_voice_pair({"voice": "af_nova,bm_george,am_echo"})


@pytest.mark.parametrize("weights", [{"af_nova": 2, "bm_george": 7}, {"af_nova": 0.1, "bm_george": 10}])
def test_remote_unrepresentable_ratio_rejected_without_rounding(weights):
    with pytest.raises(ValueError, match="whole-number blend percentages"):
        load("kokoro_adapter").remote_voice_pair({"voice_weights": weights})


def test_local_uses_native_resolver_and_retains_speed(monkeypatch):
    adapter = load("kokoro_adapter")
    seen = []
    async def ready(*args): pass
    monkeypatch.setattr(adapter, "_ensure_pipeline_for_device", ready)
    def resolver(pipeline, voice, weights):
        seen.append((voice, weights))
        return "native-mixed-pack"
    def pipeline(text, **kwargs):
        seen.append((text, kwargs))
        return []
    runtime = SimpleNamespace(_resolve_voice=resolver, _pipeline=pipeline)
    asyncio.run(adapter._synthesize_local(runtime, ["hello"], {"voice": "af_nova,bm_george", "voice_weights": {"af_nova": 2, "bm_george": 7}, "speed": 1.4}))
    assert seen == [("af_nova,bm_george", {"af_nova": 2, "bm_george": 7}), ("hello", {"voice": "native-mixed-pack", "speed": 1.4})]


def test_remote_payload_retains_auth_timeout_and_unequal_blend(monkeypatch):
    worker = load("remote_worker")
    monkeypatch.setattr(worker, "_find_worker", lambda *args: ("http://test", {}, {}))
    seen = []
    def request(url, payload, token, timeout):
        seen.append((url, payload, token, timeout))
        return {"audio": "dGVzdA=="}
    monkeypatch.setattr(worker, "_request_json", request)
    asyncio.run(worker.synthesize(sentences=["hello"], voice="af_nova", secondary_voice="bm_george", voice_blend=30,
        speed=1.4, remote_url="http://test", remote_token="test-only", remote_timeout=31))
    assert seen[0][1] == {"sentences": ["hello"], "voice": "af_nova", "voice2": "bm_george", "blend": 30, "speed": 1.4}
    assert seen[0][2:] == ("test-only", 31)


def test_voice_catalog_splits_native_expressions_and_retains_custom_ids(monkeypatch):
    module = load("voices", "api")
    monkeypatch.setattr(module, "_gpu_helper", lambda: SimpleNamespace(get_cuda_devices=lambda: []))
    handler = object.__new__(module.Voices)
    result = asyncio.run(handler.process({"voice": "af_nova,bm_george", "voice_weights": {"zz_custom": 2}}, None))
    ids = [entry["value"] for entry in result["voices"]]
    assert len(ids) == 29 and 'zz_custom' in ids
    assert 'af_nova,bm_george' not in ids
