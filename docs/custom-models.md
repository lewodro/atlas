# Custom models and speed

Atlas uses the OpenAI chat-completions interface. The model is swappable;
the Markdown memory does not belong to any model.

## Nothing to configure

Open Atlas and it probes the usual local runtimes in parallel — Ollama
(`:11434`), LM Studio (`:1234`), llama.cpp (`:8080`) and vLLM (`:8000`).
Whichever answers first is used, with its first sensible chat model. No
`.env`, no copy-paste, no restart.

In the web UI, click **⚙**: detected runtimes appear as buttons. Click one,
pick a model, hit **save**. The **model dropdown** in the top bar then switches
models per chat, instantly.

In the terminal:

```bash
atlas models                         # what is running, what is installed
atlas use qwen2.5:7b                 # switch the default model
atlas models --runtime lmstudio      # point at LM Studio's default port
atlas models --pull qwen2.5:7b       # download with Ollama, then use it
atlas check                          # confirm the model actually answers
```

A model can generate text but still be weak at tool calling or JSON
extraction. Atlas's librarian pass covers many of those failures, and the
doctor reports them honestly. On a fresh install the choices are remembered
in `data/settings.json`; delete that file to go back to auto-detection.

## Use another Ollama model (manual override)

```bash
ollama pull llama3.2:3b
cp .env.example .env
```

Then edit:

```ini
ATLAS_MODEL=llama3.2:3b
ATLAS_BASE_URL=http://127.0.0.1:11434/v1
```

Environment variables take precedence over auto-detection, so this still
works exactly as before.

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
falls back to keyword retrieval. You can also paste that endpoint straight
into the ⚙ sheet — no files, no restart.

## Bigger models, bigger machines

There is no 3B ceiling. On a machine with enough VRAM/RAM, pick a 14B–30B model
in the GUI and Atlas will use it like any other: the answer still takes one
model call, memory stays in SQLite and Markdown, and the model dropdown
remembers your choice per chat.

```ini
# Long-form work: let bigger models finish their thought.
ATLAS_MAX_TOKENS=1024
```

Embedding models are filtered out of the picker; retrieval stays local either
way. `atlas bench --model your-30b-model` re-runs the same tool-call and
recall measurements so you can see whether the bigger model is actually
better at the parts that matter, rather than just slower.

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
offload. On constrained hardware, prefer a fully offloaded 3B–7B quantized
model over a larger model that spills into system RAM. For Ollama, use
`ollama ps` to verify whether the model is on GPU. Context size is a model
setting in Ollama's `Modelfile`; do not enlarge it unless your use case needs
it, because the KV cache consumes memory.

For frequent use, set Ollama's server-side `OLLAMA_KEEP_ALIVE` so the model
does not reload between chats. This is an Ollama server setting, not an Atlas
API setting.

## Where this is going

Atlas currently does memory, modes, tools and retrieval. The next step is an
**agent loop**: planning across several model calls, editing files through
explicit tools, and checking its own work — the shape of an OpenCode-style
coding agent, but keeping the same readable, local-first harness.
