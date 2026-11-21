---
name: Project explorer
description: Explore the configured workspace, explain structure and locate relevant files
tags: [project, files, workspace, explore, structure, code]
tools: [filesystem, git_status, git_log]
---

# Project explorer

Use this when the user asks what is in a project or where something lives.

1. Start with `filesystem` list at the workspace root.
2. Read only files needed to answer. Prefer README, manifests and source entrypoints.
3. Use `git_status` and `git_log` when the project is a repository.
4. Give a short map: purpose, main folders, entrypoints, current state.
5. Do not modify anything unless the user explicitly asks for a change.

Large files are capped by the tool. Work with what is returned, not guesses.
