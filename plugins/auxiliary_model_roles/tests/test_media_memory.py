import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_stubs import FakeMemory, HostStubs, unit  # noqa: E402


KEY = "llama_cpp/embeddinggemma-2"


class MediaMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.db_dir = os.path.join(root, "db")
        self.knowledge = os.path.join(root, "knowledge")
        os.makedirs(self.db_dir)
        os.makedirs(os.path.join(self.knowledge, "solutions"))
        self.host = HostStubs(config={"embedding": {"models": {KEY: {"image": True, "audio": True}}}}, base=root)
        self.memory = FakeMemory(self.db_dir, knowledge={"custom": self.knowledge})
        self.memory.marker()
        self.host.start()
        sys.modules["plugins._memory"] = types.ModuleType("plugins._memory")
        sys.modules["plugins._memory.helpers"] = types.ModuleType("plugins._memory.helpers")
        sys.modules["plugins._memory.helpers.memory"] = self.memory.module
        self.me = self.host.load("helpers/media_embedding.py", "usr.plugins.auxiliary_model_roles.helpers.media_embedding")
        sys.modules["usr.plugins.auxiliary_model_roles.helpers"].media_embedding = self.me
        self.mm = self.host.load("helpers/media_memory.py", "usr.plugins.auxiliary_model_roles.helpers.media_memory")
        self.agent = types.SimpleNamespace(config=types.SimpleNamespace(knowledge_subdirs=["custom"]))
        self.host.http.vectors = {"image_url": [1.0, 0.0, 0.0], "input_audio": [0.0, 1.0, 0.0], "text": [0.0, 0.0, 1.0]}

    def tearDown(self):
        for name in ("plugins._memory", "plugins._memory.helpers", "plugins._memory.helpers.memory"):
            sys.modules.pop(name, None)
        self.host.stop()
        self.tmp.cleanup()

    def write(self, *parts, data=b"media"):
        path = os.path.join(self.tmp.name, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_save_stores_the_media_vector_with_a_readable_document(self):
        path = self.write("cat.png")
        doc_id = asyncio.run(self.mm.save(self.agent, path, "My cat on the sofa", "main", {"source": "chat"}))
        doc = self.memory.db.docstore._dict[doc_id]
        self.assertEqual(doc.page_content, f"My cat on the sofa\n[image file: {path}]")
        self.assertEqual(doc.metadata["media_type"], "image")
        self.assertEqual(doc.metadata["media_model"], KEY)
        self.assertEqual(doc.metadata["source"], "chat")
        self.assertEqual(len(doc.metadata["media_sha256"]), 64)
        self.assertEqual(self.memory.db.index.rows[0], [1.0, 0.0, 0.0])
        self.assertEqual(self.memory.saved, 1)

    def test_save_refuses_a_memory_built_with_another_model_or_dimension(self):
        path = self.write("cat.png")
        self.memory.marker("huggingface", "sentence-transformers/all-MiniLM-L6-v2")
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "built with huggingface"):
            asyncio.run(self.mm.save(self.agent, path))
        self.memory.marker()
        self.memory.db.index.d = 768
        with self.assertRaisesRegex(self.me.MediaEmbeddingError, "3 dimensions but memory uses 768"):
            asyncio.run(self.mm.save(self.agent, path))
        self.assertEqual(self.memory.db.docstore._dict, {})

    def test_search_by_media_scores_on_the_memory_scale(self):
        self.memory.db.add_text("t1", "text about a cat", unit([0.9, 0.1, 0.0]), {"id": "t1", "area": "main"})
        self.memory.db.add_text("t2", "unrelated", [0.0, 0.0, 1.0], {"id": "t2", "area": "main"})
        found = asyncio.run(self.mm.search(self.agent, self.write("query.png"), limit=5, threshold=0.6))
        self.assertEqual([doc.metadata["id"] for doc, _ in found], ["t1"])
        self.assertGreater(found[0][1], 0.9)
        filtered = asyncio.run(self.mm.search(self.agent, self.write("query.png"), threshold=0, filter="solutions"))
        self.assertEqual(filtered, [])

    def test_media_memories_use_their_own_higher_threshold(self):
        # normalized scores: text memory 0.85, other media 0.90 — media needs 0.95 by default
        self.memory.db.add_text("t1", "red text", unit([0.7, 0.714, 0.0]), {"id": "t1", "area": "main"})
        self.memory.db.add_text("m1", "old photo", unit([0.8, 0.6, 0.0]), {"id": "m1", "area": "main", "media_type": "image"})
        found = asyncio.run(self.mm.search(self.agent, self.write("query.png")))
        self.assertEqual([doc.metadata["id"] for doc, _ in found], ["t1"])
        found = asyncio.run(self.mm.search(self.agent, self.write("query.png"), media_threshold=0.85))
        self.assertEqual([doc.metadata["id"] for doc, _ in found], ["m1", "t1"])
        found = asyncio.run(self.mm.search(self.agent, self.write("query.png"), threshold=0.88))
        self.assertEqual([doc.metadata["id"] for doc, _ in found], ["m1"])  # an explicit threshold applies to both

    def test_repair_restores_media_vectors_after_a_text_reindex(self):
        path = self.write("cat.png")
        doc_id = asyncio.run(self.mm.save(self.agent, path, "My cat"))
        meta = dict(self.memory.db.docstore._dict[doc_id].metadata)
        self.memory.db.delete([doc_id])  # Agent Zero's rebuild re-embeds page_content as text
        self.memory.db.add_text(doc_id, "My cat", [0.0, 0.0, 1.0], meta)
        self.assertEqual(asyncio.run(self.mm.repair(self.agent)), 1)
        position = next(p for p, i in self.memory.db.index_to_docstore_id.items() if i == doc_id)
        self.assertEqual(self.memory.db.index.rows[position], [1.0, 0.0, 0.0])
        self.assertEqual(self.memory.db.docstore._dict[doc_id].page_content, "My cat")
        self.assertEqual(asyncio.run(self.mm.repair(self.agent)), 0)  # unchanged index is not rescanned
        self.mm._repaired.clear()
        self.assertEqual(asyncio.run(self.mm.repair(self.agent)), 0)  # fingerprint now matches

    def test_repair_leaves_media_the_model_no_longer_accepts(self):
        path = self.write("song.wav")
        doc_id = asyncio.run(self.mm.save(self.agent, path))
        self.host.config["embedding"]["models"][KEY]["audio"] = False
        meta = dict(self.memory.db.docstore._dict[doc_id].metadata, media_fp="stale")
        self.memory.db.delete([doc_id]); self.memory.db.add_text(doc_id, "x", [0.0, 0.0, 1.0], meta)
        self.assertEqual(asyncio.run(self.mm.repair(self.agent)), 0)

    def test_knowledge_media_is_added_kept_changed_and_removed(self):
        main_image = self.write("knowledge", "diagram.png")
        solution_audio = self.write("knowledge", "solutions", "howto.wav")
        self.write("knowledge", "clip.mp4")  # video not accepted by this model
        self.write("knowledge", "notes.md")
        counts = asyncio.run(self.mm.index_knowledge(self.agent))
        self.assertEqual((counts["added"], counts["failed"]), (2, 0))
        docs = {d.metadata["media_path"]: d for d in self.memory.db.docstore._dict.values()}
        self.assertEqual(docs[main_image].metadata["area"], "main")
        self.assertEqual(docs[solution_audio].metadata["area"], "solutions")
        self.assertTrue(docs[main_image].metadata["knowledge_source"])
        with open(os.path.join(self.db_dir, "media_knowledge.json"), encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(sorted(state), sorted([main_image, solution_audio]))
        self.assertEqual(asyncio.run(self.mm.index_knowledge(self.agent))["added"], 0)  # once per process
        self.write("knowledge", "diagram.png", data=b"changed")
        os.remove(solution_audio)
        counts = asyncio.run(self.mm.index_knowledge(self.agent, force=True))
        self.assertEqual((counts["added"], counts["removed"]), (1, 1))
        self.assertEqual([d.metadata["media_path"] for d in self.memory.db.docstore._dict.values()], [main_image])

    def test_knowledge_media_readded_when_the_index_lost_it(self):
        path = self.write("knowledge", "diagram.png")
        asyncio.run(self.mm.index_knowledge(self.agent))
        self.memory.db.delete(list(self.memory.db.docstore._dict))
        counts = asyncio.run(self.mm.index_knowledge(self.agent, force=True))
        self.assertEqual(counts["added"], 1)
        self.assertEqual([d.metadata["media_path"] for d in self.memory.db.docstore._dict.values()], [path])

    def test_switching_off_a_modality_removes_its_knowledge_media(self):
        self.write("knowledge", "diagram.png")
        asyncio.run(self.mm.index_knowledge(self.agent))
        self.host.config["embedding"]["models"][KEY]["image"] = False
        counts = asyncio.run(self.mm.index_knowledge(self.agent, force=True))
        self.assertEqual(counts["removed"], 1)
        self.assertEqual(self.memory.db.docstore._dict, {})

    def test_text_only_model_does_nothing(self):
        self.write("knowledge", "diagram.png")
        self.host.config["embedding"]["models"] = {}
        self.assertEqual(asyncio.run(self.mm.index_knowledge(self.agent))["added"], 0)
        self.assertEqual(asyncio.run(self.mm.repair(self.agent)), 0)


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.host = HostStubs(config={"embedding": {"models": {KEY: {"image": True}}}}).start()
        extension = types.ModuleType("helpers.extension")

        class Extension:
            def __init__(self, agent=None, **kwargs):
                self.agent = agent
        extension.Extension = Extension
        agent_module = types.ModuleType("agent")

        class LoopData:
            def __init__(self):
                self.extras_persistent = {}
        agent_module.LoopData = LoopData
        sys.modules.update({"helpers.extension": extension, "agent": agent_module})
        self.me = self.host.load("helpers/media_embedding.py", "usr.plugins.auxiliary_model_roles.helpers.media_embedding")
        self.mm = types.ModuleType("usr.plugins.auxiliary_model_roles.helpers.media_memory")
        self.searched = []

        async def search(agent, path, limit):
            self.searched.append((path, limit))
            doc = types.SimpleNamespace(page_content="Saved cat photo", metadata={"id": "m1", "media_path": "/old/cat.png"})
            same = types.SimpleNamespace(page_content="itself", metadata={"id": "m2", "media_path": path})
            return [(doc, 0.71), (same, 0.99)]
        self.mm.search = search
        sys.modules[self.mm.__name__] = self.mm
        pkg = sys.modules["usr.plugins.auxiliary_model_roles.helpers"]
        pkg.media_embedding, pkg.media_memory = self.me, self.mm
        self.capture = self.host.load(
            "extensions/python/_functions/agent/Agent/hist_add_user_message/start/_30_aux_media_attachments.py", "aux_capture")
        self.recall = self.host.load("extensions/python/message_loop_prompts_after/_55_aux_media_recall.py", "aux_recall")
        self.data = {}
        self.agent = types.SimpleNamespace(get_data=self.data.get, set_data=self.data.__setitem__)

    def tearDown(self):
        for name in ("helpers.extension", "agent"):
            sys.modules.pop(name, None)
        self.host.stop()

    def test_attachments_lead_to_one_recall_pass(self):
        message = types.SimpleNamespace(attachments=["/a0/usr/uploads/new.png", "/a0/usr/uploads/report.pdf"])
        self.capture.AuxMediaAttachments(self.agent).execute(data={"args": (self.agent, message), "kwargs": {}})
        self.assertEqual(self.data["_aux_media_attachments"], ["/a0/usr/uploads/new.png"])
        loop = sys.modules["agent"].LoopData()
        asyncio.run(self.recall.AuxMediaRecall(self.agent).execute(loop_data=loop))
        self.assertEqual(self.searched, [("/a0/usr/uploads/new.png", 3)])
        self.assertEqual(loop.extras_persistent["media_memories"],
                         "Memories similar to the attached media:\n- (0.71) Saved cat photo")
        asyncio.run(self.recall.AuxMediaRecall(self.agent).execute(loop_data=loop))
        self.assertEqual(len(self.searched), 1)

    def test_recall_skips_media_the_model_does_not_accept_or_when_off(self):
        self.data["_aux_media_attachments"] = ["/a0/usr/uploads/song.wav"]
        loop = sys.modules["agent"].LoopData()
        asyncio.run(self.recall.AuxMediaRecall(self.agent).execute(loop_data=loop))
        self.assertEqual((self.searched, loop.extras_persistent), ([], {}))
        self.host.config["embedding"]["recall_attachments"] = False
        self.data["_aux_media_attachments"] = ["/a0/usr/uploads/new.png"]
        asyncio.run(self.recall.AuxMediaRecall(self.agent).execute(loop_data=loop))
        self.assertEqual(self.searched, [])

    def test_message_without_media_clears_pending(self):
        self.data["_aux_media_attachments"] = ["/x.png"]
        message = types.SimpleNamespace(attachments=[])
        self.capture.AuxMediaAttachments(self.agent).execute(data={"args": (self.agent,), "kwargs": {"message": message}})
        self.assertIsNone(self.data["_aux_media_attachments"])


if __name__ == "__main__":
    unittest.main()
