import asyncio
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_stubs import HostStubs, unit  # noqa: E402


class MediaEmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host = HostStubs(config={"embedding": {"models": {"llama_cpp/embeddinggemma-2": {"image": True, "audio": True}}}},
                              keys={"openrouter": "sk-or-test"}, base=self.tmp.name).start()
        self.me = self.host.load("helpers/media_embedding.py", "usr.plugins.auxiliary_model_roles.helpers.media_embedding")

    def tearDown(self):
        self.host.stop()
        self.tmp.cleanup()

    def write(self, name, data=b"x" * 10):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_resolves_provider_defaults_keys_and_headers(self):
        local = self.me.resolve({"provider": "llama_cpp", "name": "embeddinggemma-2"})
        self.assertEqual(local.url, "http://host.docker.internal:8080/v1/embeddings")
        self.assertEqual(local.headers["Authorization"], "Bearer llama-cpp")
        self.assertEqual(local.modalities, {"image": True, "audio": True, "video": False})
        routed = self.me.resolve({"provider": "openrouter", "name": "google/embedding", "api_base": "https://openrouter.ai/api/v1/"})
        self.assertEqual(routed.url, "https://openrouter.ai/api/v1/embeddings")
        self.assertEqual(routed.headers["X-Title"], "Agent Zero")
        self.assertEqual(routed.headers["Authorization"], "Bearer sk-or-test")
        custom = self.me.resolve({"provider": "other", "name": "m", "api_base": "http://10.0.0.5:9932/v1"})
        self.assertNotIn("Authorization", custom.headers)  # "None" from the key store is not a key
        self.assertEqual(self.me.resolve({"provider": "openai", "name": "m"}).url, "https://api.openai.com/v1/embeddings")

    def test_refuses_providers_without_a_compatible_route(self):
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "no OpenAI-compatible"):
            self.me.resolve({"provider": "huggingface", "name": "sentence-transformers/all-MiniLM-L6-v2"})
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "API base"):
            self.me.resolve({"provider": "other", "name": "m"})
        with self.assertRaises(self.me.MediaEmbeddingError):
            self.me.resolve({"provider": "", "name": ""})

    def test_parts_follow_the_llama_server_and_openrouter_shapes(self):
        image = self.me.part("image", b"\x89PNG", "a.png")
        self.assertEqual(image["type"], "image_url")
        self.assertTrue(image["image_url"]["url"].startswith("data:image/png;base64,"))
        audio = self.me.part("audio", b"RIFF", "a.mp3")
        self.assertEqual(audio, {"type": "input_audio", "input_audio": {"data": "UklGRg==", "format": "mp3"}})
        video = self.me.part("video", b"\x00", "a.webm")
        self.assertTrue(video["input_video"]["url"].startswith("data:video/webm;base64,"))
        self.assertEqual(self.me.kind_of("x/clip.MOV"), "video")
        self.assertEqual(self.me.kind_of("notes.txt"), "")

    def test_embed_parts_sends_one_content_array_per_item_and_normalizes(self):
        target = self.me.resolve({"provider": "llama_cpp", "name": "embeddinggemma-2"})
        vectors = asyncio.run(self.me.embed_parts(target, [[{"type": "text", "text": "a"}], [self.me.part("image", b"1", "a.png")]]))
        request = self.host.http.requests[0]
        self.assertEqual(request["json"]["model"], "embeddinggemma-2")
        self.assertEqual(request["json"]["encoding_format"], "float")
        self.assertEqual([item["content"][0]["type"] for item in request["json"]["input"]], ["text", "image_url"])
        self.assertEqual(vectors[0], unit([3.0, 4.0, 0.0]))  # reordered by index and unit length
        self.host.http.status = 400
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "HTTP 400.*media not supported"):
            asyncio.run(self.me.embed_parts(target, [[{"type": "text", "text": "a"}]]))
        self.host.http.status, self.host.http.error = 200, sys.modules["httpx"].HTTPError("down")
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "unreachable"):
            asyncio.run(self.me.embed_parts(target, [[{"type": "text", "text": "a"}]]))

    def test_embed_file_requires_a_declared_modality_and_respects_the_size_limit(self):
        image = self.write("photo.jpg")
        kind, vector = asyncio.run(self.me.embed_file(object(), image, text="a red bicycle"))
        self.assertEqual(kind, "image")
        sent = self.host.http.requests[-1]["json"]["input"][0]["content"]
        self.assertEqual([part["type"] for part in sent], ["image_url", "text"])
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "not set to accept video"):
            asyncio.run(self.me.embed_file(object(), self.write("clip.mp4")))
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "Unsupported"):
            asyncio.run(self.me.embed_file(object(), self.write("notes.txt")))
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "not found"):
            asyncio.run(self.me.embed_file(object(), os.path.join(self.tmp.name, "gone.png")))
        self.host.config["embedding"]["max_media_mb"] = 0.000001
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "larger than"):
            asyncio.run(self.me.embed_file(object(), image))

    def test_settings_fill_defaults_and_keys_are_per_model(self):
        self.assertEqual(self.me.settings()["recall_threshold"], 0.84)
        self.assertEqual(self.me.settings()["recall_media_threshold"], 0.95)
        self.assertEqual(self.me.declared(None, "LLAMA_CPP ", " embeddinggemma-2 ")["image"], True)
        self.assertEqual(self.me.declared(None, "llama_cpp", "other-model"), {"image": False, "audio": False, "video": False})
        self.host.config["embedding"]["models"]["llama_cpp/embeddinggemma-2"]["video"] = "yes"
        self.assertFalse(self.me.declared(None, "llama_cpp", "embeddinggemma-2")["video"])


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.host = HostStubs().start()
        self.me = self.host.load("helpers/media_embedding.py", "usr.plugins.auxiliary_model_roles.helpers.media_embedding")
        self.probe = self.host.load("helpers/probe.py", "usr.plugins.auxiliary_model_roles.helpers.probe")

    def tearDown(self):
        self.host.stop()

    def test_samples_are_valid_media(self):
        png = self.probe.sample_png()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(struct.unpack(">II", png[16:24]), (64, 64))
        wav = self.probe.sample_wav()
        self.assertEqual(wav[:4], b"RIFF")
        self.assertEqual(len(wav), 44 + 32000)
        self.assertGreater(len(self.probe.samples()["video"][0]["input_video"]["url"]), 1000)

    def test_check_reports_each_modality_and_flags_dimension_mismatch(self):
        self.host.http.vectors = {"input_audio": [1.0, 0.0]}
        result = asyncio.run(self.probe.check({"provider": "llama_cpp", "name": "embeddinggemma-2"}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "llama_cpp/embeddinggemma-2")
        self.assertEqual(result["results"]["text"], {"ok": True, "dims": 3})
        self.assertTrue(result["results"]["image"]["ok"])
        self.assertFalse(result["results"]["audio"]["ok"])
        self.assertIn("text uses 3", result["results"]["audio"]["error"])
        self.assertEqual(len(self.host.http.requests), 4)

    def test_check_only_sends_requested_kinds(self):
        result = asyncio.run(self.probe.check({"provider": "llama_cpp", "name": "e"}, kinds=["image"]))
        self.assertEqual(sorted(result["results"]), ["image", "text"])


class HookTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("aux_hooks_test", Path(__file__).resolve().parents[1] / "hooks.py")
        self.hooks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hooks)

    def test_old_configs_gain_embedding_defaults(self):
        config = self.hooks.get_plugin_config(default={"tool": {}, "coding": {}})
        self.assertEqual(config["embedding"]["models"], {})
        self.assertTrue(config["embedding"]["recall_attachments"])
        kept = self.hooks.get_plugin_config(default={"embedding": {"recall_limit": 7, "models": {"a/b": {"image": True}}}})
        self.assertEqual(kept["embedding"]["recall_limit"], 7)
        self.assertEqual(kept["embedding"]["models"], {"a/b": {"image": True}})

    def test_save_validates_embedding_section(self):
        good = {"embedding": {"models": {"llama_cpp/e": {"image": True, "audio": False}}, "recall_threshold": 0.5}}
        self.assertIs(self.hooks.save_plugin_config(settings=good), good)
        for bad in ({"embedding": []}, {"embedding": {"models": {"nokey": {}}}},
                    {"embedding": {"models": {"a/b": {"image": "yes"}}}}, {"embedding": {"recall_threshold": 2}},
                    {"embedding": {"recall_limit": True}}, {"embedding": {"recall_attachments": "on"}}):
            with self.assertRaises(ValueError):
                self.hooks.save_plugin_config(settings=bad)


if __name__ == "__main__":
    unittest.main()
