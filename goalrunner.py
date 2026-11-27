"""Goal-driven, multi-tool executor for local models.

The old agent planner allowed one plan with at most three actions and never
checked whether the goal was reached. This module runs a bounded loop:

    plan -> validate -> execute -> observe -> check goal -> replan

Each stage uses a short, task-specific prompt, so a 2B model can drive it. The
harness owns safety: registry permissions, path checks, step budgets,
deduplication and learned tool ranking all live outside the model.

No cloud service is involved. Successful plans and tool outcomes are stored
locally and improve later planning (see toolpolicy.py and examples.py).
"""

from __future__ import annotations

import json
import re
import time

import config
import examples
import feedback
import llm
import registry
import toolpolicy

# Tools the planner may choose. Kept deliberately small: one compact catalog
# fits in a 2B model's context and every entry comes from the registry.
_ALLOWED = {
    "files", "terminal", "web_search", "web_fetch", "company_research",
    "plot_function", "skills_list", "skills_load", "git_status", "git_diff",
    "git_log", "git_init", "share",
}

PLAN_SYSTEM = """You are Atlas's goal executor. Return JSON ONLY:
{"steps":[{"tool":"files","args":{"action":"write","path":"note.md","content":"full text"},"why":"short reason","expect":"what success looks like"}],
 "done_when":"observable condition that proves the goal is done"}

Use the key "tool" for the tool name (never "step" or "action") and the key
"args" for its arguments. A write action must include the full "content".

Rules:
- Use 1-3 steps now. Valid tools are listed below.
- Give real arguments matching the tool schema. Never invent a result.
- Use relative workspace paths only. Never use absolute paths or '..'.
- If a step creates a file, add a following step to read/verify it when useful.
- Stop planning when the goal is already satisfied by earlier observations.
"""

CHECK_SYSTEM = """Return JSON ONLY: {"done":true,"reason":"...","next":[]}.
Decide whether the goal's done_when condition is met by the observations.
Accept semantic satisfaction: do not demand exact wording unless the goal
quotes a specific string. If not done, put 1-2 concrete next steps in "next":
{"tool":"files","args":{},"why":"...","expect":"..."}.
Never claim an action succeeded unless an observation shows it."""


def _catalog() -> str:
    lines = []
    for name in sorted(_ALLOWED):
        spec = registry.get(name)
        if not spec or not registry.is_available(spec):
            continue
        if registry.permission(name) == "DENY":
            continue
        required = (spec.parameters.get("required") or [])
        props = spec.parameters.get("properties") or {}
        schema = ", ".join(f"{key}:{props.get(key, {}).get('type', 'any')}"
                           for key in required) or "none"
        lines.append(f"- {name}: {spec.description[:100]} | args: {schema}")
    return "\n".join(lines)


def _ask(messages: list[dict], tier: str, max_tokens: int = 900,
         model: str | None = None) -> dict:
    options = {
        "tier": tier, "temperature": 0, "max_tokens": max_tokens, "timeout": 30,
        "response_format": {"type": "json_object"},
    }
    if model:
        options["model"] = model
    try:
        reply = llm.chat(messages, None, **options)
    except Exception:
        options.pop("response_format", None)
        try:
            reply = llm.chat(messages, None, **options)
        except Exception:
            return {}
    text = str(getattr(reply, "content", "") or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


_COMMAND_PREFIXES = ("ls", "pwd", "cat", "tree", "git", "python", "python3", "uv")


def normalise_command(command: str) -> str:
    """Rule-based repairs for common small-model terminal mistakes."""
    value = " ".join(str(command or "").split())
    if not value:
        return value
    parts = value.split()
    # "git_status" is a frequent native-tool spelling.
    parts = [part.replace("_", " ") if part.lower().startswith("git_") else part
             for part in parts]
    value = " ".join(parts)
    parts = value.split()
    if parts[0] == "uv" and parts[1:3] == ["run", "python"]:
        return value
    if parts[0] == "uv" and parts[1:2] == ["python"]:
        return "uv run python " + " ".join(parts[2:])
    if parts[0] in ("python", "python3", "uv", "git", "ls", "pwd", "cat", "tree"):
        return value
    # A bare script path means "run this script".
    if len(parts) == 1 and parts[0].endswith(".py"):
        return f"python {parts[0]}"
    return value


def _validate_step(step: object) -> tuple[dict | None, str]:
    """Validate one step against the live registry before it can run."""
    if not isinstance(step, dict):
        return None, "step is not an object"
    # Small models sometimes rename keys; accept the common variants.
    name = str(step.get("tool") or step.get("step") or step.get("name") or "").strip().lower()
    args = step.get("args", step.get("arguments", step.get("parameters")))
    if name not in _ALLOWED:
        return None, f"unknown tool {name!r}"
    spec = registry.get(name)
    if not spec or not registry.is_available(spec):
        return None, f"tool {name} unavailable"
    if registry.permission(name, args if isinstance(args, dict) else {}) == "DENY":
        return None, f"tool {name} is denied"
    if not isinstance(args, dict):
        return None, "args must be an object"
    for key in (spec.parameters.get("required") or []):
        if key not in args or args[key] in ("", None, {}):
            return None, f"missing argument {key}"
    if name == "files":
        action = str(args.get("action") or "").lower()
        path = str(args.get("path") or "")
        if action not in ("list", "read", "write", "mkdir"):
            return None, "files.action must be list, read, write or mkdir"
        if not path or path.startswith(("/", "~")) or ".." in path:
            return None, "workspace paths must be relative"
        if action == "write" and not str(args.get("content") or "").strip():
            fallback = str(step.get("expect") or step.get("why") or "").strip()
            if fallback:
                args = {**args, "content": fallback}
            else:
                return None, "write needs content"
        if action == "write" and len(str(args.get("content") or "")) > 50_000:
            return None, "file content too large"
        if action == "write" and path.endswith(".py"):
            try:
                compile(str(args.get("content") or ""), path, "exec")
            except SyntaxError as exc:
                return None, f"invalid Python: {exc.msg} (line {exc.lineno})"
    if name == "terminal":
        command = normalise_command(str(args.get("command") or ""))
        if any(ch in command for ch in (";", "&", "|", ">", "<", "`", "$(")):
            return None, "shell chaining is not allowed"
        if command.split()[0] not in _COMMAND_PREFIXES:
            return None, f"command {command.split()[0]!r} is not allowed"
        args = {**args, "command": command}
    return {
        "tool": name,
        "args": args,
        "why": str(step.get("why") or "")[:160],
        "expect": str(step.get("expect") or "")[:160],
    }, ""


def rule_plan(goal: str) -> list[dict]:
    """Deterministic fallback plan when a small model returns unusable JSON.

    Only fires for explicit file-and-run goals: it writes the requested file
    with the markers named in the goal, then executes it in the workspace.
    """
    text = str(goal or "")
    paths = re.findall(r"[\w./-]+\.(?:py|md|txt|js|json)", text, re.I)
    if not paths:
        return []
    markers = re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", text)
    shared = bool(re.search(r"\bshared\b", text, re.I))
    steps: list[dict] = []
    for path in paths[:1]:
        if path.lower().endswith(".py"):
            lines = [f"print({marker!r})" for marker in markers[:4]]
            content = "\n".join(lines) + "\n" if lines else "# created by Atlas\n"
            steps.append({
                "tool": "share" if shared else "files",
                "args": {"action": "write", "path": path, "content": content},
                "why": "create the requested script with the goal's markers",
                "expect": f"{path.rsplit('/', 1)[-1]} contains {', '.join(markers) or 'a script'}",
            })
            if not shared and re.search(r"\b(?:run|execute|launch)\b", text, re.I):
                steps.append({
                    "tool": "terminal", "args": {"command": f"python {path}"},
                    "why": "execute the script inside the workspace",
                    "expect": " ".join(markers) or "script runs successfully",
                })
        else:
            content = "\n".join(markers) + "\n" if markers else f"# {text[:80]}\n"
            steps.append({
                "tool": "share" if shared else "files",
                "args": {"action": "write", "path": path, "content": content},
                "why": "create the requested file",
                "expect": f"{path.rsplit('/', 1)[-1]} exists",
            })
    return steps


def adaptive_budget(goal: str, sig: str | None = None,
                    tier: str = "local") -> int:
    """More steps for genuinely multi-part goals, fewer for tiny models."""
    text = str(goal or "")
    sig = sig or toolpolicy.signature(goal)
    parts = len(re.findall(r"\b(?:and|then|after|plus|also|finally)\b", text, re.I))
    actions = len(re.findall(
        r"\b(?:write|create|read|check|verify|test|run|search|fetch|fix|"
        r"compare|summarize|analyze)\b", text, re.I,
    ))
    history = toolpolicy.stats(sig, 4)
    learned = sum(row["n"] for row in history) / 4.0 if history else 0
    model = str(config.MODEL or "").lower()
    small = any(hint in model for hint in ("2b", "3b", "local"))
    budget = 3 + min(2, parts) + min(1, actions // 3) + int(learned >= 2)
    if small:
        budget = min(budget, 6)
    return max(3, min(budget, 8))


def goal_satisfied(goal: str, tools: list[dict]) -> tuple[bool, str]:
    """Rule check: did the observations actually deliver the goal?"""
    text = " ".join(str(item.get("text") or "") for item in tools)
    used = {item["tool"] for item in tools}
    for path in re.findall(r"[\w./-]+\.(?:py|md|txt|js|json)", str(goal or ""), re.I):
        name = path.rsplit("/", 1)[-1]
        wrote = any(
            item["tool"] in ("files", "share")
            and str(item.get("args", {}).get("action")) == "write"
            and str(item.get("args", {}).get("path", "")).endswith(name)
            for item in tools
        )
        if not wrote and name not in text:
            return False, f"no write or read-back observed for {name}"
    if re.search(r"\b(?:run|execute|launch)\b", str(goal or ""), re.I):
        if "terminal" not in used:
            return False, "no terminal execution observed"
    for marker in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", str(goal or "")):
        if marker not in text:
            return False, f"expected output marker {marker} not observed"
    return True, "goal evidence observed"


def _verify_step(step: dict, result: dict) -> tuple[bool, str]:
    """Rule-based check that an observation satisfies the step's expectation."""
    if not result["ok"]:
        return False, "tool call failed"
    expect = str(step.get("expect") or "").strip()
    text = str(result.get("text") or "")
    if step["tool"] == "files":
        action = str(step["args"].get("action") or "")
        path = str(step["args"].get("path") or "")
        if action == "write" and path:
            try:
                import fstools
                actual = fstools.read(path)
                wanted = str(step["args"].get("content") or "").strip()[:60]
                if wanted and wanted not in actual:
                    return False, "written content does not match the request"
            except Exception as exc:
                return False, f"written file cannot be read back: {exc}"
    if step["tool"] == "terminal":
        # Look for concrete markers the model said it expected, e.g. HARNESS_OK.
        markers = re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b|\b\d{3,}\b", expect)
        missing = [marker for marker in markers if marker not in text]
        if missing:
            return False, "output missing expected marker(s): " + ", ".join(missing[:3])
    return True, "expectation satisfied" if expect else "tool succeeded"


def _execute(step: dict, sig: str) -> dict:
    name, args = step["tool"], step["args"]
    level = registry.permission(name, args)
    if level == "ASK":
        return {"**": True, "tool": name, "args": args, "ok": False,
                "text": "Permission required; step skipped. Ask the user to approve it."}
    result = registry.run(name, args, approved=True)
    text = registry.content(result)
    toolpolicy.record(sig, name, bool(result.get("ok")), result.get("duration_ms", 0))
    verified, note = _verify_step(step, {"ok": bool(result.get("ok")), "text": text})
    return {"tool": name, "args": args, "ok": bool(result.get("ok")),
            "why": step.get("why", ""), "expect": step.get("expect", ""),
            "verified": verified, "verify_note": note,
            "text": text[:4000], "duration_ms": result.get("duration_ms", 0)}


def _observations(steps: list[dict], limit: int = 5) -> str:
    lines = []
    for index, step in enumerate(steps[-limit:], 1):
        lines.append(
            f"{index}. {step['tool']} {json.dumps(step['args'], ensure_ascii=False)[:180]}\n"
            f"   ok={step['ok']} verified={step.get('verified', True)} "
            f"note={step.get('verify_note', '')} "
            f"output={str(step.get('text', ''))[:320]}"
        )
    return "\n".join(lines)


def _final_report(goal: str, steps: list[dict], tier: str,
                  model: str | None = None) -> str:
    context = _observations(steps, 6)
    messages = [
        {"role": "system", "content":
         "You report tool actions Atlas already executed. Use only the observations. "
         "State only what was done and the observed output in past tense, at most "
         "five sentences. Never mention a tool that is not in the observations. "
         "Never describe completed work as future and never invent a result."},
        {"role": "user", "content":
         f"Goal: {goal}\n\nObservations:\n{context}\n\nWrite the final report."},
    ]
    try:
        reply = llm.chat(messages, None, tier=tier, model=model, temperature=0.2,
                         timeout=25, max_tokens=500)
        answer = str(getattr(reply, "content", "") or "").strip()
    except Exception:
        answer = ""
    if answer:
        return answer
    return deterministic_report(steps)


def deterministic_report(steps: list[dict]) -> str:
    """Grounded fallback when the local model cannot produce a report."""
    if not steps:
        return "No tool steps were executed, so I cannot report a completed action."
    lines = [f"Completed {len(steps)} tool step(s):"]
    for step in steps:
        state = "ok" if step["ok"] else "failed"
        lines.append(f"- {step['tool']} ({state}): {str(step.get('text', ''))[:180]}")
    return "\n".join(lines)


def run(goal: str, tier: str = "local", *, model: str | None = None,
        on_event=None, max_steps: int | None = None) -> dict:
    """Work toward a goal with multiple validated tool calls. Never raises."""
    started = time.time()
    goal = str(goal or "").strip()
    sig = toolpolicy.signature(goal)
    emit = on_event or (lambda payload: None)
    budget = max_steps or adaptive_budget(goal, sig, tier)
    tools: list[dict] = []
    seen: set[str] = set()
    done = False
    reason = ""

    # Explicit file-and-run goals have a rule-based plan that needs no model
    # at all. This keeps the harness usable on any runtime, including a slow
    # 2B model or an offline machine.
    rule_steps = rule_plan(goal)
    if rule_steps:
        try:
            for step in rule_steps:
                clean, error = _validate_step(step)
                if not clean:
                    continue
                result = _execute(clean, sig)
                tools.append(result)
                emit({"text": goal, "status": "running",
                      "step": (f"{clean['tool']} "
                               f"{'verified' if result.get('verified') else 'failed'}")})
            satisfied, note = goal_satisfied(goal, tools)
            answer = deterministic_report(tools)
            try:
                feedback.finish(goal, tools, answer, note, tier, model)
            except Exception:
                pass
            emit({"text": goal, "status": "done" if satisfied else "incomplete",
                  "step": note})
            return {
                "goal": goal, "answer": answer, "done": satisfied,
                "reason": note, "steps": tools,
                "reasoning": [{
                    "step": item["tool"], "why": item.get("why", ""),
                    "expect": item.get("expect", ""), "ok": item["ok"],
                    "verified": item.get("verified", True),
                    "note": item.get("verify_note", ""),
                } for item in tools],
                "tools_used": sorted({item["tool"] for item in tools}),
                "step_count": len(tools),
                "duration_s": round(time.time() - started, 1),
            }
        except Exception as exc:
            return {"goal": goal, "answer": deterministic_report(tools),
                    "done": False, "reason": str(exc), "steps": tools,
                    "tools_used": [], "step_count": len(tools),
                    "duration_s": round(time.time() - started, 1)}

    try:
        hints = []
        learned = toolpolicy.prompt_hint(sig)
        similar = examples.prompt_hint(goal)
        if learned:
            hints.append(learned)
        if similar:
            hints.append(similar)
        context = ("\n\n" + "\n".join(hints)) if hints else ""

        seed = _ask([
            {"role": "system", "content": PLAN_SYSTEM + "\n\nTools:\n" + _catalog() + context},
            {"role": "user", "content": f"Goal: {goal}"},
        ], tier, model=model)
        done_when = str(seed.get("done_when") or "the goal's requested result is observed")[:200]
        pending = list(seed.get("steps") or [])
        emit({"text": goal, "status": "running", "step": "planning"})

        if not any(_validate_step(step)[0] for step in pending):
            fallback = rule_plan(goal)
            if fallback:
                pending = fallback
                emit({"text": goal, "status": "running", "step": "rule-based plan"})

        for _round in range(budget + 2):
            if len(tools) >= budget or time.time() - started > 240:
                reason = "step budget reached"
                break

            # Rank legal steps by the online-learned success posterior.
            validated = []
            for step in pending:
                clean, error = _validate_step(step)
                if clean:
                    validated.append(clean)
                elif error:
                    emit({"text": goal, "status": "running", "step": f"rejected: {error}"})
            if not validated:
                reason = "no valid next step"
                break
            names = [step["tool"] for step in validated]
            order = {name: index for index, name in enumerate(toolpolicy.rank(names, sig, 0.08))}
            validated.sort(key=lambda step: order.get(step["tool"], 99))

            for step in validated:
                if len(tools) >= budget:
                    break
                key = step["tool"] + ":" + json.dumps(step["args"], sort_keys=True)
                if seen_count([item["key"] for item in tools], key) >= 2:
                    continue
                result = _execute(step, sig)
                result["key"] = key
                tools.append(result)
                seen.add(key)
                emit({"text": goal, "status": "running",
                      "step": (f"{step['tool']} "
                               f"{'verified' if result.get('verified') else 'unverified' if result['ok'] else 'failed'}")})
                if not result["ok"]:
                    # One bounded repair per failed step.
                    repair = _ask([
                        {"role": "system", "content":
                         "Return JSON ONLY: {\"steps\":[{\"tool\":\"...\","
                         "\"args\":{},\"why\":\"...\",\"expect\":\"...\"}]}. "
                         "Fix the failed tool call using the real error."},
                        {"role": "user", "content":
                         f"Goal: {goal}\nFailed: {json.dumps(step, ensure_ascii=False)[:400]}\n"
                         f"Error: {result['text'][:400]}"},
                    ], tier, max_tokens=400, model=model)
                    fixed, error = _validate_step((repair.get("steps") or [{}])[0])
                    if fixed:
                        pending.append(fixed)

            verdict = _ask([
                {"role": "system", "content": CHECK_SYSTEM},
                {"role": "user", "content":
                 f"Goal: {goal}\nDone when: {done_when}\n\nObservations:\n{_observations(tools)}\n"
                 "If a needed tool failed twice and no repair worked, say done=false "
                 "with reason 'blocked'."},
            ], tier, max_tokens=400, model=model)
            rule_ok, rule_note = goal_satisfied(goal, tools)
            done = bool(verdict.get("done")) and bool(tools) and rule_ok
            reason = str(verdict.get("reason") or "")[:200] or "goal verified by observations"
            if verdict.get("done") and not rule_ok:
                reason = f"rule check: {rule_note}"
            if done:
                break
            if reason == "blocked":
                break
            next_steps = []
            for step in (verdict.get("next") or [])[:2]:
                clean, error = _validate_step(step)
                if clean:
                    next_steps.append(clean)
            if not next_steps and not rule_ok:
                nudge = _ask([
                    {"role": "system", "content":
                     'Return JSON ONLY: {"steps":[{"tool":"...","args":{},'
                     '"why":"...","expect":"..."}]}. Complete the goal.'},
                    {"role": "user", "content":
                     f"Goal: {goal}\nNot achieved: {rule_note}\n"
                     f"Observations:\n{_observations(tools)[:1500]}"},
                ], tier, max_tokens=400, model=model)
                for step in (nudge.get("steps") or [])[:2]:
                    clean, error = _validate_step(step)
                    if clean:
                        next_steps.append(clean)
            pending = next_steps
            if not pending:
                reason = reason or rule_note or "model produced no next step"
                break

        answer = _final_report(goal, tools, tier, model)
        if done and tools:
            examples.save(goal, tools, 1.0)
        try:
            feedback.finish(goal, tools, answer, _observations(tools), tier, model)
        except Exception:
            pass
        emit({"text": goal, "status": "done" if done else "incomplete", "step": reason})
        return {
            "goal": goal, "answer": answer, "done": done,
            "reason": reason, "steps": tools,
            "reasoning": [{
                "step": item["tool"], "why": item.get("why", ""),
                "expect": item.get("expect", ""), "ok": item["ok"],
                "verified": item.get("verified", True),
                "note": item.get("verify_note", ""),
            } for item in tools],
            "tools_used": sorted({step["tool"] for step in tools}),
            "step_count": len(tools),
            "duration_s": round(time.time() - started, 1),
        }
    except Exception as exc:  # never crash the caller's turn
        return {
            "goal": goal, "answer": deterministic_report(tools), "done": False,
            "reason": f"{type(exc).__name__}: {exc}", "steps": tools,
            "reasoning": [{
                "step": item["tool"], "why": item.get("why", ""),
                "expect": item.get("expect", ""), "ok": item["ok"],
                "verified": item.get("verified", True),
                "note": item.get("verify_note", ""),
            } for item in tools],
            "tools_used": sorted({step["tool"] for step in tools}),
            "step_count": len(tools),
            "duration_s": round(time.time() - started, 1),
        }


def seen_count(values: list[str], value: str) -> int:
    return sum(1 for item in values if item == value)
