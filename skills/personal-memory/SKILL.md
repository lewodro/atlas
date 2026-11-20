---
name: Personal memory
description: Recall durable facts about the user or save an explicitly stated fact
tags: [memory, remember, recall, identity, preferences, profile]
tools: [search_notes, list_memories, remember]
---

# Personal memory

Use this when the user asks what you know about them, or states a durable fact.

1. For a question, use `search_notes` and `list_memories` with the topic.
2. Synthesize only retrieved facts. Say "I don't have that saved" for gaps.
3. Never dump the whole memory store. Answer the question asked.
4. For a new fact, require an explicit statement from the user. Save one
   self-contained sentence beginning with "The user".
5. If a correction is given, use `update_memory` with the exact note name.
6. If the user asks to forget, use `forget_memory` with a specific phrase.

Historical project details may be stale. Check before calling them current.
