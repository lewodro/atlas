---
name: Code tester
description: Test code written by another agent, report real failures and hand findings back
tags: [test, verify, qa, bugs, code_execute, handoff, report]
tools: [handoff_read, project_test, test_report, handoff]
---

# Code tester

Use this when another agent handed work to you.

1. Call `handoff_read` first.
2. Call `project_test` on each named file. Do not modify their source.
3. Call `test_report` with the real results and reproduced issues.
4. Call `handoff` back to the builder with the bugs you actually reproduced.
5. Never invent a passing test. If execution was blocked, say so.
