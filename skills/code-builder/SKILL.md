---
name: Code builder
description: Build a small project by writing real files in the shared workspace and handing off to a tester
tags: [code, build, project, implement, python, game, files, handoff]
tools: [files, terminal, git_status, handoff]
---

# Code builder

Use this when asked to build or implement something.

1. Inspect the workspace first with `files` list.
2. Write the smallest working version as real files (`files` write).
3. Keep files small and readable; prefer one Python file plus a README.
4. Run `git_status` to show what changed if the workspace is a repo.
5. Call `handoff` to the tester with the exact file names and what to test.
6. Do not claim tests passed — that is the tester's job.
