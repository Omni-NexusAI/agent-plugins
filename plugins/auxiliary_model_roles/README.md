# Auxiliary Model Roles

This Agent Zero plugin adds optional Tool and Coding specialists under Main.
Both are disabled until configured. The native provider credentials remain
authoritative; enter a provider, model name, and optional API base. The models
can be hosted or local through Agent Zero's existing provider support.
Role settings are global across presets and agent profiles in this iteration.

Main delegates a bounded goal through `auxiliary_delegate`. Tool may submit
one strict JSON action to Agent Zero's native executor, which applies its
normal permission and history path. It then returns the outcome or an
escalation to Main. Coding returns code or findings to Main. Neither
specialist silently takes over the Utility model or creates a Computer model
category. Turning a role off prevents new delegation immediately; an in-flight
model request completes or reaches its timeout.

The plugin works by itself. If System 1 is installed and enabled, the two
plugins can select a specialist through the same host delegation tool. Main
System 1 is the default first decision point; its plugin settings can choose
Tool first. System 1's action eligibility still gates its direct fixed actions.

## Multimodal embedding

Some embedding models, such as EmbeddingGemma 2, place images, audio, video and
text in one vector space. Under each preset's **Embedding Model** the plugin adds
**Media input**: Image, Audio and Video switches for that provider/model, and
**Check server**, which sends one tiny sample of each kind and sets the switches
to what the server accepted. The switches are stored per provider/model, so a
preset with a text-only embedding model is unaffected.

With media input on, the same Embedding model also:

- stores media in memory through `media_memory` (`save`, `search`,
  `index_knowledge`); text searches and recall then find saved media too;
- recalls memories similar to images, audio or video attached to a message;
- adds media files in knowledge folders to memory.

Text embedding stays on Agent Zero's native path. Media goes to the model's
OpenAI-compatible `/embeddings` route as a `content` array (`image_url`,
`input_audio`, `input_video`), the shape llama.cpp `llama-server --embeddings
--mmproj` and OpenRouter accept. Providers without that route (for example
local sentence-transformers) stay text-only; nothing falls back to another model.
Media memories keep their file reference; if Agent Zero rebuilds the index from
text, the plugin re-embeds them from the file. Plugin settings set attachment
recall, its threshold, knowledge indexing, the size limit and the timeout.

Local example (EmbeddingGemma 2 GGUF with its projector; video also needs ffmpeg
on the server's PATH):

```
llama-server -m embeddinggemma-2-Q8_0.gguf --mmproj mmproj-F16.gguf --embeddings -ngl 99 --port 9932
```

Then choose provider llama.cpp, model `embeddinggemma-2`, API base
`http://host.docker.internal:9932/v1`, and click Check server. Changing the
Embedding model re-indexes memory, as in Agent Zero itself.
