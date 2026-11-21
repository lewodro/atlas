# Hidden development chronicle

- Initialize hidden devlog to record small documentation deltas out of band.
- Goal state lives in SQLite per profile; see goals.py DB path config.ROOT_DATA.
- config.py resolves ROOT_DATA relative to the repo, not the current working dir.
- Default agent behavior is wired through modes.py; coach is the startup mode.
- server.py owns the goal loop; goals.py only persists state.
