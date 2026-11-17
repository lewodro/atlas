# Custom models and speed

Atlas uses the OpenAI chat-completions interface. The model is swappable; the
Markdown memory does not belong to any model.

## Use another Ollama model

```bash
ollama pull llama3.2:3b
cp .env.example .env
```

Then edit:

```ini
ATLAS_MODEL=llama3.2:3b
ATLAS_BASE_URL=http://127.0.0.1:11434/v1
```

Run `atlas check` before starting a chat. A model can generate text but still
be weak at tool calling or JSON extraction; Atlas's librarian pass covers many
of those failures, and the doctor reports them honestly.

## Use another OpenAI-compatible runtime

Point the same settings at llama.cpp, vLLM, LM Studio, a LAN machine, or a
compatible hosted provider:

```ini
ATLAS_BASE_URL=http://192.168.1.50:8000/v1
ATLAS_API_KEY=local-key-if-required
ATLAS_MODEL=your-model-id
```

The server must implement `/v1/chat/completions`. Native tool calling and
JSON-object responses are recommended. Embeddings are optional because Atlas
falls back to keyword retrieval.

## Make it feel fast

Atlas keeps the interactive answer path to one model call: the second
librarian call runs after the answer is displayed. Retrieval tries local
keywords before asking the embedding model, avoiding needless model swapping.

Useful settings:

```ini
# Shorter answers finish sooner. Raise for long-form work.
ATLAS_MAX_TOKENS=384

# Never invoke the embedding model. Exact-word recall only.
ATLAS_RETRIEVAL=keyword
```

Actual tokens per second mainly come from model size, quantization, and GPU
offload. On constrained hardware, prefer a fully offloaded 3B-7B quantized
model over a larger model that spills into system RAM. For Ollama, use
`ollama ps` to verify whether the model is on GPU. Context size is a model
setting in Ollama's `Modelfile`; do not enlarge it unless your use case needs
it, because the KV cache consumes memory.

For frequent use, set Ollama's server-side `OLLAMA_KEEP_ALIVE` so the model
does not reload between chats. This is an Ollama server setting, not an Atlas
API setting.
