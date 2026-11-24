"""Workspace context: the local folder Atlas is allowed to work in.

Git is one fact about the workspace, not a separate cloud identity. There is
no GitHub API here and no network call.
"""

from __future__ import annotations

import fstools
import gittools


def context() -> dict:
    try:
        root = str(fstools.workspace())
        configured = True
    except fstools.ToolError as exc:
        return {
            "configured": False,
            "root": "",
            "repo": "",
            "branch": "",
            "dirty": False,
            "changed": 0,
            "is_git": False,
            "error": str(exc),
        }
    info = gittools.status_info()
    return {"configured": configured, "root": root, "error": None, **info}


def line() -> str:
    info = context()
    if not info["configured"]:
        return ""
    if not info["is_git"]:
        return f"WORKSPACE: {info['root']} (no Git repository)"
    state = "dirty" if info["dirty"] else "clean"
    return (f"WORKSPACE: {info['root']} · repo {info['repo']} · "
            f"branch {info['branch'] or 'detached'} · {state} ({info['changed']} changed)")
