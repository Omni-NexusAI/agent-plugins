## media memory
When the Embedding model accepts media, `media_memory` stores and finds images,
audio and video by their content. Text memory search also finds saved media.
Arguments: `action` is `save`, `search` or `index_knowledge`; `path` is a local
media file; `description` (save) is a short caption; `area` (save) is the
memory area; `limit`, `threshold` and `filter` (search) work as in memory_load.
If it reports the model does not accept that media, continue without it.
