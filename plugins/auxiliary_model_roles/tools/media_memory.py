from helpers.tool import Response, Tool
from usr.plugins.auxiliary_model_roles.helpers import media_embedding as me
from usr.plugins.auxiliary_model_roles.helpers import media_memory


class MediaMemory(Tool):
    async def execute(self, action: str = "", path: str = "", description: str = "", area: str = "",
                      limit: int = 5, threshold: float | None = None, filter: str = "", **kwargs) -> Response:
        try:
            if action == "save":
                doc_id = await media_memory.save(self.agent, path, description, area)
                return Response(message=f"Media memory saved with id {doc_id}.", break_loop=False)
            if action == "search":
                limit_value = max(1, min(20, int(limit or 5)))
                level = None if threshold in (None, "") else float(threshold)
                found = await media_memory.search(self.agent, path, limit_value, level, filter)
                if not found:
                    return Response(message="No memories are similar to this media.", break_loop=False)
                lines = [f"score: {score:.3f}\nid: {doc.metadata.get('id', '')}\nContent: {doc.page_content}"
                         for doc, score in found]
                return Response(message="\n\n".join(lines), break_loop=False)
            if action == "index_knowledge":
                counts = await media_memory.index_knowledge(self.agent, force=True)
                return Response(message="Knowledge media: " + ", ".join(f"{k} {v}" for k, v in counts.items()),
                                break_loop=False)
            return Response(message="Use action save, search or index_knowledge.", break_loop=False)
        except me.MediaEmbeddingError as error:
            return Response(message=f"Media memory unavailable: {error}", break_loop=False)
