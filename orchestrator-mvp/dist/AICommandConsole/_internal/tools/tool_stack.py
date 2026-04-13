from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tools.kernel_mode import load_kernel_mode


ROOT = Path(__file__).resolve().parent.parent
TOOL_STACK_PATH = ROOT / "contracts" / "tool_stack.json"


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_tool_stack() -> dict[str, Any]:
    default = {
        "version": "v1",
        "primary_interactive_surface": "Aider",
        "control_shells": ["OpenCode", "Goose"],
        "control_plane": "MetaForge",
        "long_task_executors": ["OpenHands", "Plandex", "LinkWork"],
        "development_executors": ["OpenCode"],
        "inspection_surface": "Continue",
        "final_verification_boundary": ["Verification", "Artifact"],
        "routing": [],
    }
    if not TOOL_STACK_PATH.exists():
        return default
    try:
        payload = json.loads(TOOL_STACK_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    merged = dict(default)
    merged.update(payload)
    return merged


def _code_binary() -> str | None:
    candidates = [
        r"D:\Microsoft VS Code\bin\code.cmd",
        r"D:\Microsoft VS Code\Code.exe",
        "code.cmd",
        "code",
    ]
    return next((item for item in candidates if shutil.which(item) or Path(item).exists()), None)


def _resolve_surface_path(surface: str, availability: dict[str, dict[str, Any]]) -> str | None:
    record = availability.get(surface, {})
    resolved = record.get("resolved")
    if resolved:
        return str(resolved)
    if surface == "Continue":
        return _code_binary()
    if surface == "OpenCode":
        return r"D:\codex\opencode.cmd"
    if surface == "Aider":
        return str(Path(r"D:\codex\bin\aider.cmd"))
    if surface == "Goose":
        return str(Path(r"D:\codex\bin\goose.cmd"))
    if surface == "OpenHands":
        return str(Path(r"D:\codex\bin\openhands.cmd"))
    if surface == "Plandex":
        return str(Path(r"D:\codex\bin\plandex.cmd"))
    if surface == "LinkWork":
        return _env_value("ORCH_LINKWORK_COMMAND") or str(Path(r"D:\codex\bin\linkwork.cmd"))
    if surface == "Codex":
        return str(Path(r"D:\codex\factoryctl.py"))
    return None


def detect_surface_availability() -> dict[str, dict[str, Any]]:
    def _code_extension_installed(extension_id: str) -> bool:
        try:
            code_binary = _code_binary()
            if not code_binary:
                return False
            result = subprocess.run(
                [code_binary, "--list-extensions"],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            if result.returncode != 0:
                return False
            return extension_id.lower() in {line.strip().lower() for line in result.stdout.splitlines()}
        except Exception:
            return False

    probes = {
        "Aider": [str(Path(r"D:\codex\bin\aider.cmd")), "aider", "aider.exe"],
        "OpenCode": ["opencode", "opencode.exe", "opencode.cmd"],
        "Goose": [str(Path(r"D:\codex\bin\goose.cmd")), "goose", "goose.exe"],
        "OpenHands": [str(Path(r"D:\codex\bin\openhands.cmd")), "openhands", "openhands.exe"],
        "Plandex": [str(Path(r"D:\codex\bin\plandex.cmd")), "plandex", "plandex.exe"],
        "Continue": [str(Path(r"D:\codex\bin\continue.cmd")), "continue", "continue.exe"],
        "LinkWork": [
            _env_value("ORCH_LINKWORK_COMMAND") or str(Path(r"D:\codex\bin\linkwork.cmd")),
            "linkwork",
            "linkwork.exe",
            "linkwork.cmd",
        ],
        "Codex": [str(Path(r"D:\codex\factoryctl.py"))],
    }
    result: dict[str, dict[str, Any]] = {}
    for surface, candidates in probes.items():
        if surface == "Continue":
            resolved = _code_binary() if _code_extension_installed("continue.continue") else None
        elif surface == "LinkWork":
            resolved = next((item for item in candidates if item and (shutil.which(item) or Path(item).exists())), None)
        elif surface == "Goose":
            resolved = next((item for item in candidates if shutil.which(item) or Path(item).exists()), None)
            backend_ok = False
            if resolved:
                try:
                    probe = subprocess.run(
                        [resolved, "info"],
                        capture_output=True,
                        check=False,
                        timeout=20,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    output = f"{probe.stdout or ''}{probe.stderr or ''}".lower()
                    backend_ok = probe.returncode == 0 and "version:" in output and "config dir:" in output
                except Exception:
                    backend_ok = False
            resolved = resolved if backend_ok else None
        else:
            resolved = next((item for item in candidates if shutil.which(item) or Path(item).exists()), None)
        result[surface] = {
            "available": resolved is not None,
            "resolved": resolved,
        }
    return result


def _normalize_terms(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    result: list[str] = []
    for value in values:
        text = str(value or "").strip().lower()
        if text:
            result.append(text)
    return result


def _normalize_request(request: str) -> str:
    return " ".join((request or "").strip().split()).lower()


def _launch_mode_for_surface(surface: str) -> str:
    return {
        "Aider": "message",
        "Plandex": "message",
        "Goose": "stdin",
        "OpenHands": "server",
        "OpenCode": "control",
        "Continue": "review",
        "LinkWork": "message",
        "Codex": "control",
    }.get(surface, "interactive")


def _interaction_only_active() -> bool:
    try:
        return str((load_kernel_mode() or {}).get("profile") or "").strip().lower() == "interaction_only"
    except Exception:
        return False


def _first_available_surface(availability: dict[str, dict[str, Any]], candidates: list[str]) -> str | None:
    for surface in candidates:
        if availability.get(surface, {}).get("available"):
            return surface
    return None


def _fallback_candidates_for(surface: str) -> list[str]:
    matrix = {
        "Aider": ["Goose", "Continue", "Plandex", "OpenHands"],
        "Goose": ["Aider", "Continue", "Plandex", "OpenHands"],
        "Continue": ["Goose", "Aider", "Plandex", "OpenHands"],
        "OpenHands": ["Plandex", "Goose", "Aider", "Continue"],
        "Plandex": ["OpenHands", "Goose", "Aider", "Continue"],
        "LinkWork": ["Goose", "OpenHands", "Plandex", "Aider", "Continue"],
        "OpenCode": ["Goose", "Aider", "Continue", "Plandex", "OpenHands"],
        "Codex": ["Aider", "Goose", "Continue", "Plandex", "OpenHands"],
    }
    return matrix.get(surface, ["Aider", "Goose", "Continue", "Plandex", "OpenHands"])


INTERACTION_ONLY_EXTERNAL_SURFACES = {"Aider", "Goose", "OpenHands", "Plandex", "Continue", "LinkWork"}
INTERACTION_ONLY_LOCAL_SURFACES = {"OpenCode", "Codex"}
INTERACTION_ONLY_CONTROL_SURFACES = {"Goose", "Continue"}
INTERACTION_ONLY_MUTATING_HINTS = {
    "build",
    "compile",
    "package",
    "edit",
    "fix",
    "patch",
    "refactor",
    "code",
    "repair",
    "bugfix",
    "self-repair",
    "test",
    "review",
    "pr",
    "inspect",
    "diff",
    "check",
    "run",
    "execute",
}


def _interaction_only_requires_external(request: str, task_shape: str | None = None) -> bool:
    corpus = " ".join(part for part in [request or "", task_shape or ""] if part).lower()
    return any(token in corpus for token in INTERACTION_ONLY_MUTATING_HINTS)


def _interaction_only_control_request(request: str) -> bool:
    corpus = (request or "").lower()
    return any(
        token in corpus
        for token in [
            "dispatch",
            "status",
            "control",
            "approve",
            "reject",
            "session",
            "dispatch",
            "control",
            "manage",
            "approve",
            "reject",
            "session",
        ]
    )


def _routing_rules(stack: dict[str, Any]) -> list[dict[str, Any]]:
    rules = []
    for item in stack.get("routing") or []:
        if isinstance(item, dict):
            rules.append(item)
    return rules


def _match_routing_rule(request: str, stack: dict[str, Any]) -> dict[str, Any] | None:
    normalized = _normalize_request(request)
    scored: list[tuple[int, dict[str, Any]]] = []
    for rule in _routing_rules(stack):
        keywords = _normalize_terms(rule.get("keywords"))
        task_shape = str(rule.get("task_shape") or "").strip()
        score = 0
        matched: list[str] = []
        for keyword in keywords:
            if keyword and keyword in normalized:
                score += 1
                matched.append(keyword)
        if not score and task_shape and task_shape.lower() in normalized:
            score = 1
            matched.append(task_shape.lower())
        if score:
            candidate = dict(rule)
            candidate["matched_keywords"] = matched
            candidate["score"] = score
            scored.append((score, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], str(item[1].get("preferred_surface") or ""), str(item[1].get("task_shape") or "")))
    return scored[0][1]


def _surface_profile(
    surface: str,
    *,
    availability: dict[str, dict[str, Any]],
    request: str,
    workspace: str | None,
    launch_mode: str,
) -> dict[str, Any]:
    resolved = _resolve_surface_path(surface, availability)
    workspace_path = str(Path(workspace).resolve()) if workspace else None
    effective_launch_mode = launch_mode if launch_mode not in {"", "interactive"} else _launch_mode_for_surface(surface)
    profile = {
        "surface": surface,
        "available": bool(availability.get(surface, {}).get("available")),
        "resolved": resolved,
        "launch_mode": effective_launch_mode,
        "workspace": workspace_path,
        "request": request,
    }
    if surface == "Aider":
        profile["command"] = [resolved or "aider", "--message", request, "--yes-always"]
        profile["cwd"] = workspace_path
    elif surface == "Plandex":
        profile["command"] = [resolved or "plandex", "tell", request]
        profile["cwd"] = workspace_path
    elif surface == "Goose":
        profile["command"] = [resolved or "goose", "run", "-i", "-"]
        profile["cwd"] = workspace_path
        profile["stdin_text"] = request
    elif surface == "OpenHands":
        profile["command"] = [resolved or "openhands"]
        profile["cwd"] = workspace_path or str(ROOT)
    elif surface == "OpenCode":
        profile["command"] = [resolved or r"D:\codex\opencode.cmd"]
        if workspace_path:
            profile["command"].append(workspace_path)
        profile["cwd"] = workspace_path or str(ROOT)
    elif surface == "Continue":
        code_binary = resolved or _code_binary() or r"D:\Microsoft VS Code\bin\code.cmd"
        profile["command"] = [code_binary]
        if workspace_path:
            profile["command"].append(workspace_path)
        profile["cwd"] = workspace_path or str(ROOT)
    elif surface == "Codex":
        profile["command"] = [resolved or r"D:\codex\factoryctl.py", "dispatch", request]
        profile["cwd"] = str(ROOT)
    else:
        profile["command"] = [resolved or surface.lower()]
        profile["cwd"] = workspace_path or str(ROOT)
    return profile


def _wrap_windows_command(command: list[str]) -> list[str]:
    if not command:
        return command
    first = str(command[0]).lower()
    if first.endswith(".cmd") or first.endswith(".bat"):
        return ["cmd", "/c", *command]
    return command


def recommend_surface(request: str) -> dict[str, Any]:
    text = (request or "").strip().lower()
    stack = load_tool_stack()
    availability = detect_surface_availability()
    matched_rule = _match_routing_rule(request, stack)
    interaction_only = _interaction_only_active()
    requires_external = _interaction_only_requires_external(request, matched_rule.get("task_shape") if matched_rule else None)
    control_request = _interaction_only_control_request(request)

    if matched_rule is not None:
        preferred = str(matched_rule.get("preferred_surface") or "").strip() or stack.get("primary_interactive_surface", "Aider")
        fallback = str(matched_rule.get("fallback_surface") or "").strip() or None
        reason = f"Matched task shape: {matched_rule.get('task_shape') or 'unknown'}"
        rule_launch_mode = str(matched_rule.get("launch_mode") or "interactive").strip()
    elif any(token in text for token in ["review", "pr", "inspect", "diff", "check", "audit", "verification", "artifact"]):
        preferred = "Continue"
        fallback = "OpenCode"
        reason = "PR inspection and local review request"
        rule_launch_mode = "review"
    elif any(token in text for token in ["long", "multi-step", "agent", "workflow", "execute", "run", "bootstrap", "demo", "migration", "refactor"]):
        preferred = "OpenHands" if availability.get("OpenHands", {}).get("available") else "Plandex"
        fallback = "Plandex" if preferred == "OpenHands" else "Codex"
        reason = "long-running execution request"
        rule_launch_mode = "server" if preferred == "OpenHands" else "message"
    elif any(token in text for token in ["dispatch", "status", "control", "approve", "reject", "session", "control plane", "tool stack"]):
        preferred = "OpenCode"
        fallback = "Goose"
        reason = "control-shell command request"
        rule_launch_mode = "control"
    elif any(token in text for token in ["edit", "fix", "patch", "refactor", "code", "build", "test", "repair", "bugfix"]):
        preferred = "Aider"
        fallback = "OpenCode"
        reason = "interactive coding request"
        rule_launch_mode = "message"
    else:
        preferred = stack.get("primary_interactive_surface", "Aider")
        fallback = "OpenCode"
        reason = "default interactive route"
        rule_launch_mode = "interactive"

    if interaction_only:
        if requires_external and preferred in INTERACTION_ONLY_LOCAL_SURFACES:
            preferred = _first_available_surface(
                availability,
                ["Aider", "Goose", "Plandex", "OpenHands", "Continue"],
            ) or preferred
        if control_request:
            preferred = _first_available_surface(availability, ["Goose", "Continue"]) or preferred
        if preferred == "Aider":
            fallback = _first_available_surface(availability, ["Goose", "Plandex", "OpenHands", "Continue"]) or fallback
        elif preferred == "Continue":
            fallback = _first_available_surface(availability, ["Goose", "Aider", "Plandex", "OpenHands"]) or fallback
        elif preferred in {"OpenHands", "Plandex"}:
            fallback = _first_available_surface(availability, ["Plandex", "OpenHands", "Goose", "Aider"]) or fallback
        elif preferred == "OpenCode":
            fallback = _first_available_surface(availability, ["Goose", "Aider", "Plandex", "OpenHands"]) or fallback

    selected = availability.get(preferred, {"available": False, "resolved": None})
    if not selected.get("available"):
        if interaction_only:
            if requires_external:
                fallback = fallback or _first_available_surface(availability, ["Aider", "Goose", "Plandex", "OpenHands", "Continue"])
            elif control_request:
                fallback = fallback or _first_available_surface(availability, ["Goose", "Continue", "Aider"])
            elif preferred in {"OpenHands", "Plandex"}:
                fallback = fallback or _first_available_surface(availability, ["Plandex", "OpenHands", "Goose", "Aider"])
            elif preferred == "Aider":
                fallback = fallback or _first_available_surface(availability, ["Goose", "Plandex", "OpenHands", "Continue"])
            elif preferred == "Continue":
                fallback = fallback or _first_available_surface(availability, ["Goose", "Aider", "Plandex", "OpenHands"])
            elif preferred == "OpenCode":
                fallback = fallback or _first_available_surface(availability, ["Goose", "Aider", "Plandex", "OpenHands"])
        elif preferred in {"OpenHands", "Plandex"} and availability.get("Codex", {}).get("available"):
            fallback = "Codex"
        elif preferred == "Aider" and availability.get("OpenCode", {}).get("available"):
            fallback = "OpenCode"
        elif preferred == "Continue" and availability.get("OpenCode", {}).get("available"):
            fallback = "OpenCode"
        elif preferred == "OpenCode" and availability.get("Goose", {}).get("available"):
            fallback = "Goose"
        elif not fallback and availability.get("OpenCode", {}).get("available"):
            fallback = "OpenCode"

    chosen = preferred if selected.get("available") else fallback or preferred
    launch_mode = _launch_mode_for_surface(chosen)
    profile = _surface_profile(
        chosen,
        availability=availability,
        request=request,
        workspace=str(ROOT),
        launch_mode=launch_mode,
    )
    launch_hints = {
        "Aider": "Use the Aider launcher with --message for a bounded edit session.",
        "OpenCode": r"D:\codex\opencode.cmd",
        "Goose": "Use `goose run` with stdin or an instruction file.",
        "OpenHands": "Start the OpenHands local server and use the browser URL.",
        "Plandex": "Use `plandex tell` for a long running plan/task session.",
        "LinkWork": "Run the LinkWork executor command with a standardized JSON handoff bundle on stdin.",
        "Continue": "Open the workspace in VS Code and use the Continue extension.",
        "Codex": "D:\\codex\\factoryctl.py dispatch \"<task>\"",
    }

    return {
        "request": request,
        "reason": reason,
        "task_shape": matched_rule.get("task_shape") if matched_rule else None,
        "matched_keywords": matched_rule.get("matched_keywords") if matched_rule else [],
        "interaction_only": interaction_only,
        "requires_external_executor": requires_external,
        "rule_launch_mode": rule_launch_mode,
        "preferred_surface": preferred,
        "preferred_available": bool(selected.get("available")),
        "preferred_resolved": selected.get("resolved"),
        "fallback_surface": fallback,
        "fallback_available": bool(availability.get(fallback, {}).get("available")) if fallback else False,
        "availability": availability,
        "launch_mode": launch_mode,
        "launch_hint": launch_hints.get(chosen),
        "next_step_command": " ".join(str(part) for part in profile.get("command") or []),
        "launch_command": profile.get("command"),
        "launch_cwd": profile.get("cwd"),
        "launch_stdin_text": profile.get("stdin_text"),
        "dispatchable": bool(matched_rule.get("dispatchable", True)) if matched_rule else True,
        "tool_stack": stack,
    }


def route_task(request: str, *, workspace: str | None = None) -> dict[str, Any]:
    route = recommend_surface(request)
    route["workspace"] = workspace
    if workspace:
        preferred = str(route.get("preferred_surface") or "").strip()
        fallback = str(route.get("fallback_surface") or "").strip()
        surface = preferred if route.get("preferred_available") else fallback or preferred
        availability = route.get("availability", {})
        launch_mode = _launch_mode_for_surface(surface)
        profile = _surface_profile(
            surface,
            availability=availability,
            request=request,
            workspace=workspace,
            launch_mode=launch_mode,
        )
        route["launch_mode"] = profile.get("launch_mode")
        route["launch_command"] = profile.get("command")
        route["launch_cwd"] = profile.get("cwd")
        route["launch_stdin_text"] = profile.get("stdin_text")
        route["next_step_command"] = " ".join(str(part) for part in profile.get("command") or [])
        route["launch_hint"] = route["next_step_command"]
    return route


def launch_task(request: str, *, workspace: str | None = None, prefer: str | None = None) -> dict[str, Any]:
    route = route_task(request, workspace=workspace)
    preferred = str(route.get("preferred_surface") or "").strip()
    fallback = str(route.get("fallback_surface") or "").strip()
    surface = str(prefer or (preferred if route.get("preferred_available") else fallback or preferred) or "").strip()
    interaction_only = _interaction_only_active()
    control_request = _interaction_only_control_request(request)
    requires_external = bool(route.get("requires_external_executor"))
    if not surface:
        return {
            "ok": False,
            "reason": "No surface could be resolved for this request.",
            "route": route,
        }
    availability = route.get("availability", {})
    if interaction_only:
        if control_request:
            surface = _first_available_surface(availability, ["Goose", "Continue"]) or surface
        elif requires_external or surface in INTERACTION_ONLY_LOCAL_SURFACES:
            surface = _first_available_surface(availability, ["Aider", "Goose", "Plandex", "OpenHands", "Continue"]) or surface
        if surface in INTERACTION_ONLY_LOCAL_SURFACES and requires_external:
            return {
                "ok": False,
                "reason": "interaction_only mode requires an external executor; no external surface is available.",
                "route": route,
            }
    if not availability.get(surface, {}).get("available"):
        if surface == "OpenHands" and availability.get("Plandex", {}).get("available"):
            surface = "Plandex"
        elif surface == "Aider" and availability.get("OpenCode", {}).get("available"):
            surface = "OpenCode"
        elif surface == "Continue" and availability.get("OpenCode", {}).get("available"):
            surface = "OpenCode"
    profile = _surface_profile(
        surface,
        availability=availability,
        request=request,
        workspace=workspace,
        launch_mode=str(route.get("launch_mode") or "interactive"),
    )
    command = profile.get("command") or []
    cwd = profile.get("cwd")
    stdin_text = profile.get("stdin_text")
    if not command:
        return {
            "ok": False,
            "reason": f"Surface '{surface}' does not expose a launch command.",
            "route": route,
        }
    launch_mode = str(profile.get("launch_mode") or "interactive")
    if surface in {"Aider", "Continue", "OpenCode", "OpenHands"} or launch_mode in {"server", "control", "review"}:
        wrapped = _wrap_windows_command([str(part) for part in command])
        process = subprocess.Popen(
            wrapped,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            text=True,
        )
        return {
            "ok": True,
            "mode": "background",
            "surface": surface,
            "pid": process.pid,
            "command": wrapped,
            "cwd": str(cwd) if cwd else None,
            "interaction_only": interaction_only,
            "requires_external_executor": requires_external,
            "route": route,
            "summary": f"Launched {surface} in the background.",
        }

    wrapped = _wrap_windows_command([str(part) for part in command])
    completed = subprocess.run(
        wrapped,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin_text,
        check=False,
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    output = "\n".join(part for part in [stdout.strip(), stderr.strip()] if part).strip()
    return {
        "ok": completed.returncode == 0,
        "mode": "one-shot",
        "surface": surface,
        "returncode": completed.returncode,
        "command": wrapped,
        "cwd": str(cwd) if cwd else None,
        "stdout": stdout,
        "stderr": stderr,
        "route": route,
        "interaction_only": interaction_only,
        "requires_external_executor": requires_external,
        "summary": output or f"Completed {surface} launch with return code {completed.returncode}.",
    }


