# 30 real-model tests

Model: `qwen2.5:3b` via local Ollama. Each prompt ran in a fresh session with a real streaming response. No mocked outputs.

| # | Prompt | Tools | Result |
|---|---|---|---|
| 1 | Who am I? Don't guess. | - | pass |
| 2 | What am I studying at university? | - | pass |
| 3 | What sport do I play and what is my background? | - | pass |
| 4 | What are my major programming interests? | - | pass |
| 5 | What are my long-term goals? | - | pass |
| 6 | Explain Big O notation in under 100 words. | - | pass |
| 7 | Study quadratic functions: define, plot f(x)=x**2, and giv | - | needs follow-up |
| 8 | What is the derivative of x**3? Show the rule and one valu | plot_function+ | pass |
| 9 | Summarize the idea of active recall in three lines. | - | pass |
| 10 | Make condensed study notes on linked lists with a small di | plot_function+, files+ | pass |
| 11 | Draw f(x)=sin(x) and name two properties. | plot_function+, git_status+, git_diff+ | pass |
| 12 | Explain the difference between RAM and storage simply. | - | pass |
| 13 | Search the web for Python list tutorial and give one fact  | web_search+, web_fetch+ | pass |
| 14 | Fetch https://example.com and tell me what it says. | web_fetch+ | pass |
| 15 | Research what Ollama is using web search and cite a source | web_search+, web_fetch+, git_status+ | pass |
| 16 | Fetch a page about HTTP status codes and give me one code. | web_search+, git_status+, git_diff+, web_fetch- | needs follow-up |
| 17 | Use the files tool to list my workspace. | files+ | pass |
| 18 | Write notes.md with '# Study notes' using the files tool. | files+ | pass |
| 19 | Read notes.md back and tell me its content. | files- | needs follow-up |
| 20 | Use mkdir to create a folder demos then list the workspace | terminal-, terminal- | needs follow-up |
| 21 | Delete notes.md with the files tool, then list. | files+, files+ | pass |
| 22 | Use terminal ls and tell me the files. | terminal+ | pass |
| 23 | Use terminal git status and report the state. | terminal+, git_status+, git_diff+ | pass |
| 24 | Use git_log and tell me the latest commit. | git_log- | needs follow-up |
| 25 | Check the git diff of my workspace. | git_diff+ | pass |
| 26 | What do you know about Last Seat? | git_log- | needs follow-up |
| 27 | What should you do if you don't have a fact about me? | - | pass |
| 28 | How do I prefer to learn programming? | - | pass |
| 29 | /skill:study Write three revision questions on calculus. | - | needs follow-up |
| 30 | /goal Inspect the workspace with files, then report how ma | files+ | pass |

Initial run: 23/30 passed. Seven needed follow-up:
- two empty answers from an overlong 9 KB system prompt → fixed with a 4.2 KB prompt budget; both now answer.
- `mkdir` via terminal was rejected → deterministic file-tool routing added; now works.
- `notes.md` read failed after the model wrote `notes/notes.md` → child-folder path fallback added.
- `git_log` failed on a repo with no commits → correct behaviour, not a bug.
- one invented image link and one tool-result contradiction → prompt rules added.

Post-fix retest examples (real Qwen):
- quadratic plot → `plot_function` called, parabola explained.
- `/skill:study` revision questions → `skills_load` called, three questions returned.
- mkdir + list → `files` mkdir then terminal ls, both ok.
- write/read notes.md → both ok with the child-folder fallback.
