from agent import LoopData
from helpers.extension import Extension

from usr.plugins.auxiliary_model_roles.helpers import media_embedding as me
from usr.plugins.auxiliary_model_roles.helpers import media_memory


PENDING = "_aux_media_attachments"


class AuxMediaRecall(Extension):
    """Recall memories similar to media the user attached, through the multimodal Embedding model."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return
        paths = self.agent.get_data(PENDING)
        if not paths:
            return
        self.agent.set_data(PENDING, None)
        options = me.settings(self.agent)
        if not options["recall_attachments"]:
            return
        try:
            target = me.current(self.agent)
        except me.MediaEmbeddingError:
            return
        seen, lines = set(), []
        for path in paths:
            if not target.modalities.get(me.kind_of(path)):
                continue
            try:
                found = await media_memory.search(self.agent, path, int(options["recall_limit"]))
            except me.MediaEmbeddingError:
                continue
            for doc, score in found:
                doc_id = doc.metadata.get("id")
                if doc_id in seen or doc.metadata.get("media_path") == path:
                    continue
                seen.add(doc_id)
                lines.append(f"- ({score:.2f}) {doc.page_content}")
        if lines:
            loop_data.extras_persistent["media_memories"] = (
                "Memories similar to the attached media:\n" + "\n".join(lines))
