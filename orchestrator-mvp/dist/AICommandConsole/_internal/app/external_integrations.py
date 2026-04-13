from __future__ import annotations

import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .config import read_external_integration_config


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _env_value(name: str) -> str:
    return os.getenv(name, "").strip()


def _probe_http(url: str, *, timeout_seconds: int) -> dict[str, Any]:
    if not url:
        return {
            "status": "disabled",
            "reachable": False,
            "healthy": False,
            "response_code": None,
            "detail": "No status URL configured.",
        }
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_code = int(getattr(response, "status", 200))
            if 200 <= response_code < 300:
                status = "healthy"
                healthy = True
                reachable = True
                detail = "HTTP probe returned a successful response."
            elif response_code in {401, 403}:
                status = "auth_required"
                healthy = False
                reachable = True
                detail = "HTTP probe reached the service but authentication is required."
            elif response_code < 500:
                status = "reachable"
                healthy = False
                reachable = True
                detail = "HTTP probe reached the service."
            else:
                status = "unreachable"
                healthy = False
                reachable = False
                detail = f"Unexpected response code {response_code}."
            return {
                "status": status,
                "reachable": reachable,
                "healthy": healthy,
                "response_code": response_code,
                "detail": detail,
            }
    except urllib.error.HTTPError as exc:
        response_code = int(getattr(exc, "code", 0) or 0) or None
        if response_code in {401, 403}:
            return {
                "status": "auth_required",
                "reachable": True,
                "healthy": False,
                "response_code": response_code,
                "detail": exc.reason or str(exc),
            }
        if response_code is not None and response_code < 500:
            return {
                "status": "reachable",
                "reachable": True,
                "healthy": False,
                "response_code": response_code,
                "detail": exc.reason or str(exc),
            }
        return {
            "status": "unreachable",
            "reachable": False,
            "healthy": False,
            "response_code": response_code,
            "detail": exc.reason or str(exc),
        }
    except Exception as exc:
        return {
            "status": "unreachable",
            "reachable": False,
            "healthy": False,
            "response_code": None,
            "detail": str(exc),
        }


def load_external_integration_bindings() -> list[dict[str, Any]]:
    config = read_external_integration_config()
    bindings = config.get("bindings") if isinstance(config, dict) else []
    return list(bindings) if isinstance(bindings, list) else []


def collect_external_integration_status(*, executor_manager: Any | None = None) -> dict[str, Any]:
    config = read_external_integration_config()
    timeout_seconds = int(config.get("probe_timeout_seconds") or 5)
    services: list[dict[str, Any]] = []
    for binding in load_external_integration_bindings():
        kind = str(binding.get("kind") or "http").strip().lower()
        base_url = str(binding.get("base_url") or "").strip()
        status_url = str(binding.get("status_url") or "").strip()
        executor_id = str(binding.get("executor_id") or "").strip()
        api_key_configured = bool(binding.get("api_key_configured"))
        if kind == "executor":
            health: dict[str, Any] = {
                "status": "disabled",
                "reachable": False,
                "healthy": False,
                "detail": "Executor manager unavailable.",
            }
            if executor_manager is not None and executor_id:
                adapter = executor_manager.get_adapter(executor_id)
                if adapter is not None:
                    health = dict(adapter.healthcheck())
                    health.setdefault("status", "healthy" if health.get("healthy", False) else "degraded")
                    health.setdefault("reachable", bool(health.get("healthy", False)))
                    health.setdefault("detail", "Executor healthcheck completed.")
                else:
                    health = {
                        "status": "unavailable",
                        "reachable": False,
                        "healthy": False,
                        "detail": f"Executor '{executor_id}' is unavailable.",
                    }
            services.append(
                {
                    **binding,
                    "checked_at": _utc_now(),
                    "health": health,
                    "auth_configured": api_key_configured,
                }
            )
            continue
        probe_url = status_url or base_url
        health = _probe_http(probe_url, timeout_seconds=timeout_seconds)
        services.append(
            {
                **binding,
                "checked_at": _utc_now(),
                "health": health,
                "auth_configured": api_key_configured,
            }
        )
    summary = {
        "total": len(services),
        "healthy": sum(1 for item in services if bool(((item.get("health") or {}).get("healthy")))),
        "reachable": sum(1 for item in services if bool(((item.get("health") or {}).get("reachable")))),
        "configured": sum(1 for item in services if bool(item.get("base_url") or item.get("executor_id"))),
    }
    return {
        "updated_at": _utc_now(),
        "summary": summary,
        "services": services,
    }
