from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CODEX_ROOT = ROOT
PYTHON_EXE = CODEX_ROOT / "tools" / "python311-embed" / "python.exe"
FACTORYCTL_PY = CODEX_ROOT / "factoryctl.py"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator-mvp"))
sys.path.insert(0, str(ROOT / "orchestrator-mvp" / ".venv" / "Lib" / "site-packages"))

from tools.execution_engine import python_command, run_hidden
from tools.tool_stack import launch_task, recommend_surface, route_task


def _invoke_factoryctl(*args: str) -> subprocess.CompletedProcess[str]:
    command = python_command(FACTORYCTL_PY, *args, interpreter=PYTHON_EXE)
    result = run_hidden(command, cwd=CODEX_ROOT)
    return subprocess.CompletedProcess(command, result.returncode, result.stdout, result.stderr)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _collect_json(*args: str) -> Any:
    result = _invoke_factoryctl(*args)
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if result.returncode != 0:
        return {
            "_error": True,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    text = result.stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return text


def _load_ai_risk_payload() -> dict[str, Any]:
    report = CODEX_ROOT / "orchestrator-mvp" / "data" / "ai_test_status.json"
    status_cache = CODEX_ROOT / "orchestrator-mvp" / "data" / "status_cache.json"
    daemon_state = CODEX_ROOT / "orchestrator-mvp" / "data" / "factory_daemon_state.json"

    payload = {
        "status": "missing",
        "pass_rate": 0.0,
        "error_count": 0,
        "failing_case_ids": [],
        "updated_at": None,
    }
    if report.exists():
        payload.update(_load_json(report, {}))

    cache_payload = _load_json(status_cache, {})
    daemon_payload = _load_json(daemon_state, {})
    ai_system = cache_payload.get("ai_testing") or {}

    threshold = ai_system.get("threshold", payload.get("threshold"))
    if threshold is None:
        threshold = daemon_payload.get("ai_testing_threshold", 3)

    consecutive_failures = ai_system.get("consecutive_failures", payload.get("consecutive_failures"))
    if consecutive_failures is None:
        consecutive_failures = daemon_payload.get("ai_testing_consecutive_failures")
    if consecutive_failures is None:
        status_value = ai_system.get("status", payload.get("status", "missing"))
        error_count = ai_system.get("error_count", payload.get("error_count", 0)) or 0
        consecutive_failures = 1 if status_value in {"degraded", "attention", "missing"} or int(error_count) > 0 else 0

    alert = ai_system.get("alert", payload.get("alert"))
    if alert is None:
        alert = daemon_payload.get("ai_testing_alert")
    if alert is None:
        alert = bool(threshold is not None and consecutive_failures >= threshold)

    return {
        "status": payload.get("status") or ai_system.get("status"),
        "provider": payload.get("provider") or ai_system.get("provider"),
        "api_style": payload.get("api_style") or ai_system.get("api_style"),
        "model": payload.get("model") or ai_system.get("model"),
        "pass_rate": payload.get("pass_rate") if payload.get("pass_rate") is not None else ai_system.get("pass_rate"),
        "error_count": payload.get("error_count") if payload.get("error_count") is not None else ai_system.get("error_count"),
        "error_types": payload.get("error_types", []) or ai_system.get("error_types", []),
        "max_attempt_count": payload.get("max_attempt_count") if payload.get("max_attempt_count") is not None else ai_system.get("max_attempt_count"),
        "retry_policy": payload.get("retry_policy", {}) or ai_system.get("retry_policy", {}),
        "attempted_providers": payload.get("attempted_providers", []) or ai_system.get("attempted_providers", []),
        "failing_case_ids": (payload.get("failing_case_ids", []) or ai_system.get("failing_case_ids") or [])[:5],
        "consecutive_failures": consecutive_failures,
        "alert": alert,
        "threshold": threshold,
        "updated_at": payload.get("updated_at") or ai_system.get("updated_at"),
    }


def _format_rate(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.0%}"
    return str(value)


def _print_status_summary() -> None:
    light = _collect_json("light-status")
    ai = _collect_json("ai-test-status")
    stack = _collect_json("tool-stack-status", "--refresh")

    if not isinstance(light, dict):
        print("系统状态摘要：无法读取 light-status。")
        return

    daemon = light.get("daemon", {})
    control_layer = light.get("control_layer", {})
    engineering_os = light.get("engineering_os", {})
    tool_health = light.get("tool_health", {})
    release_ops = light.get("release_ops", {})
    ai_payload = ai if isinstance(ai, dict) else {}
    stack_payload = stack.get("tool_stack", stack) if isinstance(stack, dict) else {}
    availability = stack_payload.get("availability", {}) if isinstance(stack_payload, dict) else {}
    primary = stack_payload.get("primary_interactive_surface", "Aider") if isinstance(stack_payload, dict) else "Aider"
    primary_state = "可用" if availability.get(primary, {}).get("available") else "不可用"

    print("系统状态摘要：")
    print(f"- 守护进程：{daemon.get('status') or '未知'}，cycle {daemon.get('cycle') or '未知'}")
    print(f"- 控制层：{control_layer.get('status') or '未知'}")
    print(f"- 工程系统：{engineering_os.get('status') or '未知'}，patch gate {engineering_os.get('patch_gate_status') or '未知'}")
    print(f"- 工具健康：{tool_health.get('status') or '未知'}")
    print(f"- 发布链：{release_ops.get('status') or '未知'}，下一步 {release_ops.get('next_action') or '未知'}")
    print(f"- AI 测试：{ai_payload.get('status') or '未知'}，通过率 {_format_rate(ai_payload.get('pass_rate'))}")
    print(f"- 首选入口：{primary}（{primary_state}）")
    failing = ai_payload.get("failing_case_ids") or []
    if failing:
        print(f"- 主要失败项：{', '.join(failing[:5])}")


def _print_tool_stack_summary() -> None:
    payload = _collect_json("tool-stack-status", "--refresh")
    if not isinstance(payload, dict):
        print("工具栈摘要：无法读取工具栈状态。")
        return
    stack = payload.get("tool_stack", payload)
    availability = stack.get("availability", {}) if isinstance(stack, dict) else {}

    def state(name: str) -> str:
        return "可用" if availability.get(name, {}).get("available") else "不可用"

    print("工具栈摘要：")
    print(f"- 主交互入口：{stack.get('primary_interactive_surface', 'Aider')}（{state(stack.get('primary_interactive_surface', 'Aider'))}）")
    print(f"- 控制壳：{', '.join(stack.get('control_shells', [])) or '未配置'}")
    print(f"- 长任务执行器：{', '.join(stack.get('long_task_executors', [])) or '未配置'}")
    print(f"- 开发执行器：{', '.join(stack.get('development_executors', [])) or '未配置'}")
    print(f"- 复核入口：{stack.get('inspection_surface', 'Continue')}（{state(stack.get('inspection_surface', 'Continue'))}）")
    print(f"- 最终裁决层：{' / '.join(stack.get('final_verification_boundary', [])) or '未配置'}")


def _print_route_summary(request: str) -> None:
    routed = route_task(request, workspace=str(CODEX_ROOT))
    preferred = routed.get("preferred_surface")
    fallback = routed.get("fallback_surface")
    chosen = preferred if routed.get("preferred_available") else fallback or preferred or "未命中"
    print(f"我建议这条请求走：{chosen}。")
    print(f"- 请求：{request}")
    print(f"- 原因：{routed.get('reason') or '未说明'}")
    if routed.get("task_shape"):
        print(f"- 任务形状：{routed.get('task_shape')}")
    print(f"- 首选入口：{preferred}（{'可用' if routed.get('preferred_available') else '不可用'}）")
    if fallback:
        print(f"- 回退入口：{fallback}（{'可用' if routed.get('fallback_available') else '不可用'}）")
    if routed.get("launch_mode"):
        print(f"- 启动模式：{routed.get('launch_mode')}")
    hint = routed.get("launch_hint") or routed.get("next_step_command")
    if hint:
        print(f"- 下一步：{hint}")
    command = routed.get("launch_command") or []
    if command:
        print(f"- 启动命令：{' '.join(str(part) for part in command)}")


def _print_task_launch_summary(result: dict[str, Any]) -> None:
    route = result.get("route") or {}
    surface = result.get("surface") or route.get("preferred_surface") or route.get("fallback_surface") or "未命中"
    print(f"任务已路由到：{surface}")
    if route.get("task_shape"):
        print(f"- 任务形状：{route.get('task_shape')}")
    if route.get("launch_mode"):
        print(f"- 启动模式：{route.get('launch_mode')}")
    if result.get("command"):
        print(f"- 启动命令：{' '.join(str(part) for part in result.get('command') or [])}")
    if result.get("cwd"):
        print(f"- 工作目录：{result.get('cwd')}")
    if result.get("pid"):
        print(f"- 进程号：{result.get('pid')}")
    if result.get("summary"):
        print(f"- 反馈：{result.get('summary')}")


def _print_ai_risk_summary() -> None:
    summary = _load_ai_risk_payload()
    print(
        f"AI 风险摘要：状态 {summary.get('status') or '未知'}，模型 {summary.get('model') or '未知'}，"
        f"通过率 {_format_rate(summary.get('pass_rate'))}，失败数 {summary.get('error_count', 0)}，"
        f"告警 {'开启' if summary.get('alert') else '关闭'}。"
    )
    failing = summary.get("failing_case_ids") or []
    if failing:
        print(f"- 主要失败项：{', '.join(failing[:5])}")


def _print_ai_test_summary(payload: Any) -> None:
    if not isinstance(payload, dict):
        print(payload)
        return
    status = payload.get("status") or "未知"
    pass_rate = payload.get("pass_rate")
    print(f"AI 测试状态：{status}，通过率 {_format_rate(pass_rate)}，错误数 {payload.get('error_count', 0)}。")
    failing = payload.get("failing_case_ids") or []
    if failing:
        print(f"- 主要失败项：{', '.join(failing[:5])}")


def _print_simple_status(command: str, payload: Any) -> None:
    if not isinstance(payload, dict):
        print(payload)
        return
    if command == "daemon-status":
        daemon = payload.get("daemon", payload)
        print(f"守护进程：{daemon.get('status') or '未知'}，cycle {daemon.get('cycle') or '未知'}。")
        return
    if command == "control-layer-status":
        status = payload.get("status") or payload.get("control_policy", {}).get("mode") or "未知"
        quality = (payload.get("quality_system") or {}).get("status") or "未知"
        eng = (payload.get("engineering_os") or {}).get("status") or "未知"
        release = (payload.get("release_operations") or {}).get("status") or "未知"
        print(f"控制层：{status}，质量系统 {quality}，工程系统 {eng}，发布链 {release}。")
        return
    if command == "engineering-os-status":
        eng = payload.get("engineering_os", payload)
        print(
            f"工程系统：{eng.get('status') or '未知'}，patch gate {eng.get('patch_gate_status') or '未知'}，"
            f"release gate {eng.get('release_gate_status') or '未知'}。"
        )
        return
    if command == "lab-status":
        org = (payload.get("organization_unit") or {}).get("name") or "未知"
        status = payload.get("status") or "未知"
        print(f"实验室：{status}，组织单元 {org}。")
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _parse_session_token(raw_args: list[str]) -> tuple[str | None, list[str]]:
    session_token = None
    cleaned_args: list[str] = []
    idx = 0
    while idx < len(raw_args):
        arg = raw_args[idx]
        if arg in {"--SessionToken", "-SessionToken", "--session-token", "-session-token"} and idx + 1 < len(raw_args):
            session_token = raw_args[idx + 1]
            idx += 2
            continue
        cleaned_args.append(arg)
        idx += 1
    return session_token, cleaned_args


def _parse_mode(raw_args: list[str]) -> tuple[str, bool, list[str]]:
    mode = "nl"
    route_full = False
    cleaned: list[str] = []
    for arg in raw_args:
        if arg in {"--json", "-j"}:
            mode = "json"
            continue
        if arg == "--nl":
            mode = "nl"
            continue
        if arg in {"--route-full", "--full-route"}:
            route_full = True
            continue
        cleaned.append(arg)
    return mode, route_full, cleaned


def _strip_prefix(text: str, prefixes: list[str]) -> str:
    stripped = text.strip()
    lowered = stripped.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix.lower()):
            return stripped[len(prefix) :].strip().lstrip(":, ")
    return stripped


def _intent(text: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    compact = re.sub(r"\s+", "", normalized.lower())
    if not normalized:
        return "status", ""

    if any(key in compact for key in ["toolstack", "tool-stack", "executorstack", "工具栈", "执行器栈", "入口推荐", "推荐入口", "哪个入口", "该用哪个", "应该用哪个"]):
        return "tool-stack", normalized
    if any(key in compact for key in ["airisk", "ai-risk", "ai风险", "风险摘要", "ai安全", "ai summary"]):
        return "ai-risk", ""
    if any(key in compact for key in ["aitestrun", "ai-test-run", "ai测试运行", "执行aitest", "runaitests", "跑测试"]):
        return "ai-test-run", ""
    if any(key in compact for key in ["aiteststatus", "ai-test-status", "ai测试状态", "ai测试", "模型测试", "测试状态"]):
        return "ai-test-status", ""
    if any(key in compact for key in ["sessionopen", "开会话", "新会话", "打开会话", "建立会话"]):
        return "session-open", ""
    if any(key in compact for key in ["sessionclose", "关会话", "关闭会话", "结束会话"]):
        return "session-close", ""
    if any(key in compact for key in ["dispatch", "派发", "分派", "下发任务", "执行这个任务", "帮我执行", "帮我做"]):
        return "dispatch", _strip_prefix(normalized, ["dispatch", "派发", "分派", "下发任务", "执行这个任务", "帮我执行", "帮我做"])
    if any(key in compact for key in ["launchtask", "tasklaunch", "launch", "execute task", "run task", "启动", "执行任务", "直接执行", "落地", "跑起来"]):
        return "task-launch", _strip_prefix(normalized, ["launch", "execute task", "run task", "task-launch", "启动", "执行任务", "直接执行", "落地", "跑起来"])
    if any(key in compact for key in ["approve", "批准", "通过", "同意", "确认"]):
        return "approve", _strip_prefix(normalized, ["approve", "批准", "通过", "同意", "确认"])
    if any(key in compact for key in ["reject", "拒绝", "驳回", "否决", "退回"]):
        return "reject", _strip_prefix(normalized, ["reject", "拒绝", "驳回", "否决", "退回"])
    if any(key in compact for key in ["daemonstatus", "守护进程", "daemon", "当前守护"]):
        return "daemon-status", ""
    if any(key in compact for key in ["controllayer", "控制层", "control-layer"]):
        return "control-layer-status", ""
    if any(key in compact for key in ["engineeringos", "工程系统", "engineering-os"]):
        return "engineering-os-status", ""
    if any(key in compact for key in ["labstatus", "实验室", "lab状态"]):
        return "lab-status", ""
    if any(key in compact for key in ["status", "状态", "看一下系统", "系统如何", "系统怎么样", "当前情况", "概况"]):
        return "status", ""
    if any(key in compact for key in ["route", "推荐", "应该用", "该用", "怎么用", "用哪个", "入口", "选择", "修复", "构建", "编译", "代码", "测试", "重构", "补丁"]):
        return "route", _strip_prefix(normalized, ["route", "推荐", "应该用", "该用", "怎么用", "用哪个", "入口", "选择"])
    if any(key in compact for key in ["smokehygiene", "smoke-hygiene", "smoke清理", "清理smoke", "清理烟雾", "噪音清理", "历史smoke"]):
        return "smoke-hygiene", _strip_prefix(normalized, ["smoke-hygiene", "smoke hygiene", "清理", "整理", "清理smoke", "噪音清理"])
    return "route", normalized


def _emit_json_or_text(value: Any, json_mode: bool) -> int:
    if json_mode:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


def _route_snapshot(payload: Any, *, full: bool = False) -> Any:
    if full or not isinstance(payload, dict):
        return payload
    if "preferred_surface" not in payload and "fallback_surface" not in payload:
        return payload

    availability_payload = payload.get("availability")
    availability: dict[str, bool] = {}
    if isinstance(availability_payload, dict):
        for surface, record in availability_payload.items():
            if isinstance(record, dict):
                availability[str(surface)] = bool(record.get("available"))
            else:
                availability[str(surface)] = bool(record)

    preferred = payload.get("preferred_surface")
    fallback = payload.get("fallback_surface")
    chosen = preferred if payload.get("preferred_available") else fallback or preferred

    snapshot = {
        "snapshot": "route.v1.compact",
        "request": payload.get("request"),
        "reason": payload.get("reason"),
        "task_shape": payload.get("task_shape"),
        "preferred_surface": preferred,
        "preferred_available": bool(payload.get("preferred_available")),
        "fallback_surface": fallback,
        "fallback_available": bool(payload.get("fallback_available")),
        "chosen_surface": chosen,
        "launch_mode": payload.get("launch_mode"),
        "next_step_command": payload.get("next_step_command"),
        "requires_external_executor": bool(payload.get("requires_external_executor")),
        "dispatchable": bool(payload.get("dispatchable", True)),
        "interaction_only": bool(payload.get("interaction_only")),
        "availability": availability,
        "workspace": payload.get("workspace"),
        "diagnostics_hint": "Use --route-full to include full route diagnostics.",
    }
    return snapshot


def main() -> int:
    raw_args = list(sys.argv[1:])
    output_mode, route_full, raw_args = _parse_mode(raw_args)
    json_mode = output_mode == "json"
    session_token, cleaned_args = _parse_session_token(raw_args)
    text = " ".join(cleaned_args).strip()
    if not text:
        print("请输入自然语言请求，例如：查看系统状态、推荐我该用哪个入口、派发修复任务。")
        return 1

    command, remainder = _intent(text)

    if command == "status":
        if json_mode:
            payload = {
                "light": _collect_json("light-status"),
                "ai": _collect_json("ai-test-status"),
                "stack": _collect_json("tool-stack-status", "--refresh"),
            }
            return _emit_json_or_text(payload, True)
        _print_status_summary()
        return 0

    if command == "tool-stack":
        if json_mode:
            return _emit_json_or_text(_collect_json("tool-stack-status", "--refresh"), True)
        _print_tool_stack_summary()
        return 0

    if command == "route":
        if json_mode:
            routed = route_task(remainder or text, workspace=str(CODEX_ROOT))
            return _emit_json_or_text(_route_snapshot(routed, full=route_full), True)
        _print_route_summary(remainder or text)
        return 0

    if command == "task-route":
        payload = route_task(remainder or text, workspace=str(CODEX_ROOT))
        if json_mode:
            payload = _route_snapshot(payload, full=route_full)
        return _emit_json_or_text(payload, json_mode)

    if command == "smoke-hygiene":
        payload = _collect_json("smoke-hygiene")
        if json_mode:
            return _emit_json_or_text(payload, True)
        if isinstance(payload, dict):
            cleanup = payload.get("smoke_noise_cleanup_count", 0)
            print(f"烟雾清理：完成，归档 {cleanup} 个历史 smoke 任务。")
            reconciled = payload.get("reconciled_smoke") or {}
            if reconciled:
                print(f"- 收口任务：{reconciled.get('completed_smoke_tasks', 0)}")
            delivery = payload.get("delivery_summary") or {}
            if delivery:
                print(
                    f"- 交付统计：released {delivery.get('released_tasks', 0)}，"
                    f"completed {delivery.get('completed_tasks', 0)}"
                )
            return 0
        return _emit_json_or_text(payload, False)

    if command == "ai-risk":
        if json_mode:
            return _emit_json_or_text(_load_ai_risk_payload(), True)
        _print_ai_risk_summary()
        return 0

    if command == "ai-test-status":
        payload = _collect_json("ai-test-status")
        if json_mode:
            return _emit_json_or_text(payload, True)
        _print_ai_test_summary(payload)
        return 0

    if command == "ai-test-run":
        payload = _collect_json("ai-test-run")
        return _emit_json_or_text(payload, json_mode)

    if command == "daemon-status":
        payload = _collect_json("daemon-status")
        if json_mode:
            return _emit_json_or_text(payload, True)
        _print_simple_status("daemon-status", payload)
        return 0

    if command == "control-layer-status":
        payload = _collect_json("control-layer-status")
        if json_mode:
            return _emit_json_or_text(payload, True)
        _print_simple_status("control-layer-status", payload)
        return 0

    if command == "engineering-os-status":
        payload = _collect_json("engineering-os-status")
        if json_mode:
            return _emit_json_or_text(payload, True)
        _print_simple_status("engineering-os-status", payload)
        return 0

    if command == "lab-status":
        payload = _collect_json("lab-status")
        if json_mode:
            return _emit_json_or_text(payload, True)
        _print_simple_status("lab-status", payload)
        return 0

    if command == "session-open":
        payload = _collect_json("session-open", "--owner", "opencode-control", "--role", "operator")
        if json_mode:
            return _emit_json_or_text(payload, True)
        if isinstance(payload, dict):
            token = payload.get("token") or payload.get("session_token")
            owner = payload.get("owner") or payload.get("session", {}).get("owner")
            print(f"会话已打开：{owner or '未知所有者'}。")
            if token:
                print(f"会话令牌：{token}")
            return 0
        return _emit_json_or_text(payload, False)

    if command == "session-close":
        if not session_token:
            print("关闭会话需要先提供 --SessionToken <token>。请先执行 `opencode-control.ps1 session-open` 获取令牌。")
            return 1
        payload = _collect_json("--session-token", session_token, "session-close")
        return _emit_json_or_text(payload, json_mode)

    if command in {"dispatch", "approve", "reject"}:
        if not session_token:
            action = "派发任务" if command == "dispatch" else "批准" if command == "approve" else "拒绝"
            print(f"{action}需要会话令牌。请先执行 `opencode-control.ps1 session-open`。")
            return 1
        task = remainder or text
        payload = _collect_json("--session-token", session_token, command, task)
        if json_mode:
            return _emit_json_or_text(payload, True)
        if isinstance(payload, dict):
            status = payload.get("status") or payload.get("result") or "已完成"
            print(f"{command} 已执行：{status}。")
            return 0
        return _emit_json_or_text(payload, False)

    if command == "task-launch":
        result = launch_task(remainder or text, workspace=str(CODEX_ROOT))
        if json_mode:
            return _emit_json_or_text(result, True)
        _print_task_launch_summary(result)
        return 0

    if command == "self-report":
        payload = _collect_json("self-report")
        return _emit_json_or_text(payload, json_mode)

    # Unknown input: treat it as a routing request.
    if json_mode:
        routed = route_task(text, workspace=str(CODEX_ROOT))
        return _emit_json_or_text(_route_snapshot(routed, full=route_full), True)
    _print_route_summary(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
