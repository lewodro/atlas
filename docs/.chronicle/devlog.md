# Hidden development chronicle

- Initialize hidden devlog to record small documentation deltas out of band.
- Goal state lives in SQLite per profile; see goals.py DB path config.ROOT_DATA.
- config.py resolves ROOT_DATA relative to the repo, not the current working dir.
- Default agent behavior is wired through modes.py; coach is the startup mode.
- server.py owns the goal loop; goals.py only persists state.
- Profiles isolate memory, goals, and artifacts under data/profiles.
- llm.py centralizes provider calls so models.py can swap backends cleanly.
- models.py --use switches the active model for the current profile.
- memory.py exposes both stats and semantic recall through the atlas CLI.
- activity.py --scan appends a timestamped activity snapshot.
- consolidate.py folds recent activity into long-term notes during sleep.
- tools_cli.py is the dispatch surface for tools, skills, and artifacts.
- registry.py tracks which tools and skills are currently registered.
