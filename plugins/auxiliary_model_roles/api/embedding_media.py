from helpers.api import ApiHandler, Request, Response

from usr.plugins.auxiliary_model_roles.helpers import media_embedding as me
from usr.plugins.auxiliary_model_roles.helpers import probe


class EmbeddingMedia(ApiHandler):
    """Check server for the Embedding model's media input. Keys stay server-side."""

    async def process(self, input: dict, request: Request) -> dict | Response:
        if input.get("action") != "probe":
            return Response(status=400, response="Unknown action")
        cfg = {key: input.get(key) for key in ("provider", "name", "api_base")}
        cfg["kwargs"] = input.get("kwargs") if isinstance(input.get("kwargs"), dict) else {}
        cfg["kwargs"].pop("api_key", None)
        kinds = [kind for kind in input.get("modalities") or me.MODALITIES if kind in me.MODALITIES]
        try:
            return await probe.check(cfg, kinds, timeout=float(me.settings()["timeout_seconds"]))
        except me.MediaEmbeddingError as error:
            return {"ok": False, "error": str(error), "results": {}}
