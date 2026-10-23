import asyncio

from agent import LoopData
from helpers.extension import Extension

from usr.plugins.auxiliary_model_roles.helpers import media_embedding as me
from usr.plugins.auxiliary_model_roles.helpers import media_memory


_tasks: dict[str, asyncio.Task] = {}


class AuxMediaMemory(Extension):
    """Keep media memories on media vectors and bring knowledge-folder media in, in the background."""

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return
        try:
            target = me.current(self.agent)
        except me.MediaEmbeddingError:
            return
        if not any(target.modalities.values()):
            return
        key = f"{id(self.agent.context)}:{target.key}"
        if key in _tasks and not _tasks[key].done():
            return
        _tasks[key] = asyncio.create_task(self._run(target))

    async def _run(self, target):
        agent = self.agent
        try:
            fixed = await media_memory.repair(agent)
            counts = {"added": 0, "removed": 0, "failed": 0}
            if me.settings(agent)["index_knowledge_media"]:
                counts = await media_memory.index_knowledge(agent)
            if fixed or counts["added"] or counts["removed"] or counts["failed"]:
                agent.context.log.log(type="util", heading="Media memory updated",
                                      content=(f"Re-embedded {fixed}; knowledge media added {counts['added']}, "
                                               f"removed {counts['removed']}, failed {counts['failed']} "
                                               f"with {target.key}."))
        except Exception as error:
            agent.context.log.log(type="util", heading="Media memory not updated", content=type(error).__name__)
