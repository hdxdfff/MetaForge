from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _promote_proxy_env() -> None:
    proxy_url = os.getenv("ORCH_NETWORK_PROXY_URL", "").strip()
    if not proxy_url:
        return
    if not os.getenv("HTTP_PROXY"):
        os.environ["HTTP_PROXY"] = proxy_url
    if not os.getenv("HTTPS_PROXY"):
        os.environ["HTTPS_PROXY"] = proxy_url


_promote_proxy_env()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _default_shell_backend() -> str:
    configured = os.getenv("ORCH_SHELL_BACKEND", "").strip().lower()
    if configured in {"open-interpreter", "subprocess", "docker"}:
        return configured
    interpreter_cmd = os.getenv(
        "ORCH_OPEN_INTERPRETER_CMD", r"D:\codex\open-interpreter.cmd"
    ).strip()
    if interpreter_cmd and Path(interpreter_cmd).exists():
        return "open-interpreter"
    return "subprocess"


def _is_coding_plan_base_url(base_url: str) -> bool:
    normalized = (base_url or "").strip().lower().rstrip("/")
    return "/api/coding" in normalized


def _normalize_coding_plan_model(model: str, base_url: str, *, default_model: str) -> str:
    normalized = (model or "").strip().lower()
    if normalized and normalized != "auto":
        return model.strip()
    if _is_coding_plan_base_url(base_url):
        return default_model
    return default_model


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = _first_env(
        "CODING_PLAN_API_KEY",
        "VOLCENGINE_API_KEY",
        "ARK_API_KEY",
        "OPENAI_API_KEY",
        default="",
    )
    openai_base_url: str = _first_env(
        "CODING_PLAN_BASE_URL",
        "VOLCENGINE_BASE_URL",
        "ARK_BASE_URL",
        "OPENAI_BASE_URL",
        default="https://api.openai.com/v1",
    )
    openai_base_url_candidates: list[str] = None  # type: ignore[assignment]
    openai_proxy_candidates: list[str] = None  # type: ignore[assignment]
    openai_api_style: str = _first_env(
        "CODING_PLAN_API_STYLE",
        "VOLCENGINE_API_STYLE",
        "ARK_API_STYLE",
        "OPENAI_API_STYLE",
        default="auto",
    )
    planner_model: str = _first_env(
        "CODING_PLAN_MODEL",
        "VOLCENGINE_MODEL_CODING_PLAN",
        "ARK_MODEL_CODING_PLAN",
        "OPENAI_MODEL_PLANNER",
        default="minimax-m2.5",
    )
    smart_model_routing_enabled: bool = os.getenv("ORCH_SMART_MODEL_ROUTING_ENABLED", "true").lower() == "true"
    model_usage_ratio_sample_min_calls: int = int(os.getenv("ORCH_MODEL_RATIO_SAMPLE_MIN_CALLS", "5"))
    model_usage_max_reasoning_ratio: float = float(os.getenv("ORCH_MODEL_MAX_REASONING_RATIO", "0.6"))
    model_usage_max_strong_ratio: float = float(os.getenv("ORCH_MODEL_MAX_STRONG_RATIO", "0.15"))
    planner_escalation_model: str = _first_env(
        "CODING_PLAN_ESCALATION_MODEL",
        "VOLCENGINE_MODEL_CODING_PLAN_ESCALATION",
        "ARK_MODEL_CODING_PLAN_ESCALATION",
        "OPENAI_MODEL_PLANNER_ESCALATION",
        default="kimi-k2.5",
    )
    architect_model: str = _first_env(
        "CODING_PLAN_ARCHITECT_MODEL",
        "VOLCENGINE_MODEL_CODING_PLAN_ARCHITECT",
        "ARK_MODEL_CODING_PLAN_ARCHITECT",
        "OPENAI_MODEL_ARCHITECT",
        "OPENAI_MODEL_PLANNER_ESCALATION",
        default="kimi-k2.5",
    )
    cheap_llm_api_key: str = os.getenv("CHEAP_LLM_API_KEY", "")
    cheap_llm_base_url: str = os.getenv("CHEAP_LLM_BASE_URL", "http://localhost:11434")
    cheap_llm_base_url_candidates: list[str] = None  # type: ignore[assignment]
    cheap_llm_proxy_candidates: list[str] = None  # type: ignore[assignment]
    reasoning_llm_api_key: str = os.getenv("REASONING_LLM_API_KEY", os.getenv("CHEAP_LLM_API_KEY", ""))
    reasoning_llm_base_url: str = os.getenv("REASONING_LLM_BASE_URL", os.getenv("CHEAP_LLM_BASE_URL", "http://localhost:11434"))
    reasoning_llm_base_url_candidates: list[str] = None  # type: ignore[assignment]
    reasoning_llm_proxy_candidates: list[str] = None  # type: ignore[assignment]
    reasoning_planner_model: str = os.getenv("OPENAI_MODEL_PLANNER_REASONING", "deepseek-reasoner")
    reasoning_coder_model: str = os.getenv("OPENAI_MODEL_CODER_REASONING", "deepseek-reasoner")
    reasoning_review_model: str = os.getenv("OPENAI_MODEL_REVIEW_REASONING", "deepseek-reasoner")
    cheap_coder_model: str = os.getenv("OPENAI_MODEL_CODER_CHEAP", "coder")
    cheap_review_model: str = os.getenv("OPENAI_MODEL_REVIEW_CHEAP", "reviewer")
    cheap_summary_model: str = os.getenv("OPENAI_MODEL_SUMMARY_CHEAP", "summary")
    expensive_coder_model: str = os.getenv("OPENAI_MODEL_CODER_EXPENSIVE", "gpt-5-codex")
    default_simple_task_model: str = os.getenv("ORCH_DEFAULT_SIMPLE_TASK_MODEL", "")
    default_review_model: str = os.getenv("ORCH_DEFAULT_REVIEW_MODEL", "")
    default_publish_check_model: str = os.getenv("ORCH_DEFAULT_PUBLISH_CHECK_MODEL", "")
    cheap_max_calls_per_task: int = int(os.getenv("ORCH_CHEAP_MAX_CALLS_PER_TASK", "12"))
    cheap_max_chars_per_task: int = int(os.getenv("ORCH_CHEAP_MAX_CHARS_PER_TASK", "24000"))
    cheap_loop_repeat_threshold: int = int(os.getenv("ORCH_CHEAP_LOOP_REPEAT_THRESHOLD", "2"))
    cheap_max_output_chars: int = int(os.getenv("ORCH_CHEAP_MAX_OUTPUT_CHARS", "5000"))
    cheap_request_timeout_seconds: float = float(os.getenv("ORCH_CHEAP_REQUEST_TIMEOUT_SECONDS", "45"))
    reasoning_request_timeout_seconds: float = float(os.getenv("ORCH_REASONING_REQUEST_TIMEOUT_SECONDS", "90"))
    planner_request_timeout_seconds: float = float(os.getenv("ORCH_PLANNER_REQUEST_TIMEOUT_SECONDS", "60"))
    llm_max_retries: int = int(os.getenv("ORCH_LLM_MAX_RETRIES", "3"))
    llm_retry_base_seconds: float = float(os.getenv("ORCH_LLM_RETRY_BASE_SECONDS", "2"))
    llm_retry_max_seconds: float = float(os.getenv("ORCH_LLM_RETRY_MAX_SECONDS", "12"))
    provider_gateway_enabled: bool = os.getenv("ORCH_PROVIDER_GATEWAY_ENABLED", "true").lower() == "true"
    provider_route_max_attempts: int = int(os.getenv("ORCH_PROVIDER_ROUTE_MAX_ATTEMPTS", "3"))
    provider_route_backoff_seconds: float = float(os.getenv("ORCH_PROVIDER_ROUTE_BACKOFF_SECONDS", "1.5"))
    provider_circuit_failure_threshold: int = int(os.getenv("ORCH_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", "2"))
    provider_circuit_cooldown_seconds: int = int(os.getenv("ORCH_PROVIDER_CIRCUIT_COOLDOWN_SECONDS", "300"))
    max_escalations_per_task: int = int(os.getenv("ORCH_MAX_ESCALATIONS_PER_TASK", "2"))
    core_escalation_on_cheap_failure: bool = os.getenv("ORCH_CORE_ESCALATION_ON_CHEAP_FAILURE", "true").lower() == "true"
    approval_mode: str = os.getenv("ORCH_APPROVAL_MODE", "manual")
    real_execution_enabled: bool = os.getenv("ORCH_ENABLE_REAL_EXECUTION", "false").lower() == "true"
    shell_backend: str = _default_shell_backend()
    open_interpreter_cmd: str = os.getenv("ORCH_OPEN_INTERPRETER_CMD", "D:\\codex\\open-interpreter.cmd")
    docker_executable: str = os.getenv("ORCH_DOCKER_EXE", "docker")
    docker_image: str = os.getenv("ORCH_DOCKER_IMAGE", "python:3.11-slim")
    docker_workdir: str = os.getenv("ORCH_DOCKER_WORKDIR", "/work")
    allowed_workdirs: list[str] = None  # type: ignore[assignment]
    allowed_command_prefixes: list[str] = None  # type: ignore[assignment]
    denied_command_patterns: list[str] = None  # type: ignore[assignment]
    network_agent_enabled: bool = os.getenv("ORCH_NETWORK_AGENT_ENABLED", "true").lower() == "true"
    network_probe_urls: list[str] = None  # type: ignore[assignment]
    network_poll_seconds: int = int(os.getenv("ORCH_NETWORK_POLL_SECONDS", "30"))
    network_proxy_url: str = os.getenv("ORCH_NETWORK_PROXY_URL", os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", "")))
    network_proxy_candidates: list[str] = None  # type: ignore[assignment]
    network_no_proxy: list[str] = None  # type: ignore[assignment]
    perplexity_api_key: str = os.getenv("PERPLEXITY_API_KEY", "")
    perplexity_base_url: str = os.getenv("PERPLEXITY_BASE_URL", "https://api.perplexity.ai")
    perplexity_base_url_candidates: list[str] = None  # type: ignore[assignment]
    perplexity_proxy_candidates: list[str] = None  # type: ignore[assignment]
    perplexity_model: str = os.getenv("PERPLEXITY_MODEL", "sonar-pro")
    perplexity_request_timeout_seconds: float = float(os.getenv("ORCH_PERPLEXITY_REQUEST_TIMEOUT_SECONDS", "45"))
    embedding_provider: str = os.getenv("ORCH_EMBEDDING_PROVIDER", "local")
    embedding_model: str = os.getenv("ORCH_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    embedding_dimensions: int = int(os.getenv("ORCH_EMBEDDING_DIMENSIONS", "128"))
    repo_learning_max_files: int = int(os.getenv("ORCH_REPO_LEARNING_MAX_FILES", "120"))
    repo_learning_max_file_chars: int = int(os.getenv("ORCH_REPO_LEARNING_MAX_FILE_CHARS", "4000"))
    github_token: str = _first_env(
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ORCH_GITHUB_APP_INSTALLATION_TOKEN",
        "GITHUB_APP_INSTALLATION_TOKEN",
        default="",
    )
    github_api_url: str = _first_env(
        "ORCH_GITHUB_API_URL",
        "GITHUB_API_URL",
        default="https://api.github.com",
    )
    github_auth_mode: str = _first_env(
        "ORCH_GITHUB_AUTH_MODE",
        "GITHUB_AUTH_MODE",
        default="auto",
    )
    github_app_id: str = os.getenv("ORCH_GITHUB_APP_ID", "")
    github_app_installation_id: str = os.getenv("ORCH_GITHUB_APP_INSTALLATION_ID", "")
    github_app_owner: str = os.getenv("ORCH_GITHUB_APP_OWNER", "")
    github_app_private_key_path: str = os.getenv("ORCH_GITHUB_APP_PRIVATE_KEY_PATH", "")
    github_learning_topics: list[str] = None  # type: ignore[assignment]
    github_learning_languages: list[str] = None  # type: ignore[assignment]
    github_learning_clone_root: str = os.getenv("ORCH_GITHUB_LEARNING_CLONE_ROOT", "D:\\codex\\orchestrator-mvp\\workspace\\github-learning")
    github_learning_scan_limit: int = int(os.getenv("ORCH_GITHUB_LEARNING_SCAN_LIMIT", "12"))
    github_learning_registration_limit: int = int(os.getenv("ORCH_GITHUB_LEARNING_REGISTRATION_LIMIT", "8"))
    github_learning_min_stars: int = int(os.getenv("ORCH_GITHUB_LEARNING_MIN_STARS", "500"))
    github_learning_live_scan: bool = os.getenv("ORCH_GITHUB_LEARNING_LIVE_SCAN", "false").lower() == "true"
    host: str = os.getenv("ORCH_WEB_HOST", "127.0.0.1")
    port: int = int(os.getenv("ORCH_WEB_PORT", "8787"))

    def __post_init__(self) -> None:
        resolved_planner_model = _normalize_coding_plan_model(
            self.planner_model,
            self.openai_base_url,
            default_model="minimax-m2.5",
        )
        object.__setattr__(self, "planner_model", resolved_planner_model)
        object.__setattr__(
            self,
            "planner_escalation_model",
            _normalize_coding_plan_model(
                self.planner_escalation_model,
                self.openai_base_url,
                default_model="kimi-k2.5",
            ),
        )
        object.__setattr__(
            self,
            "architect_model",
            _normalize_coding_plan_model(
                self.architect_model,
                self.openai_base_url,
                default_model="kimi-k2.5",
            ),
        )
        object.__setattr__(
            self,
            "openai_base_url_candidates",
            _split_csv(
                _first_env(
                    "CODING_PLAN_BASE_URL_CANDIDATES",
                    "VOLCENGINE_BASE_URL_CANDIDATES",
                    "ARK_BASE_URL_CANDIDATES",
                    "OPENAI_BASE_URL_CANDIDATES",
                    default=self.openai_base_url,
                )
            ),
        )
        object.__setattr__(
            self,
            "openai_proxy_candidates",
            _split_csv(
                _first_env(
                    "CODING_PLAN_PROXY_CANDIDATES",
                    "VOLCENGINE_PROXY_CANDIDATES",
                    "ARK_PROXY_CANDIDATES",
                    "OPENAI_PROXY_CANDIDATES",
                    "ORCH_NETWORK_PROXY_CANDIDATES",
                    "ORCH_NETWORK_PROXY_URL",
                    "HTTPS_PROXY",
                    "HTTP_PROXY",
                    default="",
                )
            ),
        )
        object.__setattr__(self, "cheap_llm_base_url_candidates", _split_csv(os.getenv("CHEAP_LLM_BASE_URL_CANDIDATES", self.cheap_llm_base_url)))
        object.__setattr__(self, "cheap_llm_proxy_candidates", _split_csv(os.getenv("CHEAP_LLM_PROXY_CANDIDATES", os.getenv("ORCH_NETWORK_PROXY_CANDIDATES", os.getenv("ORCH_NETWORK_PROXY_URL", os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", "")))))))
        object.__setattr__(self, "reasoning_llm_base_url_candidates", _split_csv(os.getenv("REASONING_LLM_BASE_URL_CANDIDATES", self.reasoning_llm_base_url)))
        object.__setattr__(self, "reasoning_llm_proxy_candidates", _split_csv(os.getenv("REASONING_LLM_PROXY_CANDIDATES", os.getenv("ORCH_NETWORK_PROXY_CANDIDATES", os.getenv("ORCH_NETWORK_PROXY_URL", os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", "")))))))
        object.__setattr__(self, "allowed_workdirs", _split_csv(os.getenv("ORCH_ALLOWED_WORKDIRS", "D:\\codex")))
        object.__setattr__(self, "allowed_command_prefixes", _split_csv(os.getenv("ORCH_ALLOWED_COMMAND_PREFIXES", "python,python3,pytest,npm,node,docker,git,pwsh,powershell,bash,sh,make,cmake,gcc,ld,nasm,qemu-system-x86_64,qemu-system-i386,mysql,mysqldump,mysqladmin,ping,curl,wget,ip,ss,netstat,nc,tcpdump,traceroute")))
        object.__setattr__(self, "denied_command_patterns", _split_csv(os.getenv("ORCH_DENIED_COMMAND_PATTERNS", "rm -rf,del /f,format ,mkfs,dd if=,shutdown,reboot,poweroff,init 0,git reset --hard,git clean -fd")))
        object.__setattr__(self, "network_probe_urls", _split_csv(os.getenv("ORCH_NETWORK_PROBE_URLS", "https://example.com,https://www.baidu.com,https://www.qq.com")))
        object.__setattr__(self, "network_proxy_candidates", _split_csv(os.getenv("ORCH_NETWORK_PROXY_CANDIDATES", os.getenv("ORCH_NETWORK_PROXY_URL", os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", ""))))))
        object.__setattr__(self, "network_no_proxy", _split_csv(os.getenv("ORCH_NETWORK_NO_PROXY", os.getenv("NO_PROXY", "127.0.0.1,localhost"))))
        object.__setattr__(self, "perplexity_base_url_candidates", _split_csv(os.getenv("PERPLEXITY_BASE_URL_CANDIDATES", self.perplexity_base_url)))
        object.__setattr__(self, "perplexity_proxy_candidates", _split_csv(os.getenv("PERPLEXITY_PROXY_CANDIDATES", os.getenv("ORCH_NETWORK_PROXY_CANDIDATES", os.getenv("ORCH_NETWORK_PROXY_URL", os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", "")))))))
        object.__setattr__(self, "github_learning_topics", _split_csv(os.getenv("ORCH_GITHUB_LEARNING_TOPICS", "agent,llm,compiler,kernel,robotics,distributed-system,inference")))
        object.__setattr__(self, "github_learning_languages", _split_csv(os.getenv("ORCH_GITHUB_LEARNING_LANGUAGES", "Python,TypeScript,Rust,C++,C,Go")))
        if not self.default_simple_task_model:
            object.__setattr__(self, "default_simple_task_model", self.cheap_summary_model)
        if not self.default_review_model:
            object.__setattr__(self, "default_review_model", self.cheap_review_model)
        if not self.default_publish_check_model:
            object.__setattr__(self, "default_publish_check_model", self.cheap_summary_model)


settings = Settings()


def strategic_llm_api_style() -> str:
    style = (settings.openai_api_style or "").strip().lower()
    if style in {"responses", "chat.completions"}:
        return style
    base_url = (settings.openai_base_url or "").strip().lower().rstrip("/")
    if base_url in {"https://api.openai.com/v1", "https://api.openai.com"}:
        return "responses"
    return "chat.completions"


def read_network_runtime_config() -> dict[str, object]:
    load_dotenv(override=False)
    return {
        "enabled": os.getenv("ORCH_NETWORK_AGENT_ENABLED", "true").lower() == "true",
        "probe_urls": _split_csv(os.getenv("ORCH_NETWORK_PROBE_URLS", "https://example.com,https://www.baidu.com,https://www.qq.com")),
        "poll_seconds": int(os.getenv("ORCH_NETWORK_POLL_SECONDS", "30")),
        "proxy_url": os.getenv("ORCH_NETWORK_PROXY_URL", os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", ""))),
        "proxy_candidates": _split_csv(os.getenv("ORCH_NETWORK_PROXY_CANDIDATES", os.getenv("ORCH_NETWORK_PROXY_URL", os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", ""))))),
        "no_proxy": _split_csv(os.getenv("ORCH_NETWORK_NO_PROXY", os.getenv("NO_PROXY", "127.0.0.1,localhost"))),
    }


def _integration_binding(
    *,
    name: str,
    role: str,
    kind: str,
    base_env: str,
    status_env: str,
    api_key_env: str,
    executor_id_env: str | None = None,
) -> dict[str, object]:
    base_url = os.getenv(base_env, "").strip()
    status_url = os.getenv(status_env, "").strip()
    api_key = os.getenv(api_key_env, "").strip()
    executor_id = os.getenv(executor_id_env, "").strip() if executor_id_env else ""
    return {
        "name": name,
        "role": role,
        "kind": kind,
        "base_url": base_url or None,
        "status_url": status_url or None,
        "api_key_configured": bool(api_key),
        "executor_id": executor_id or ("openhands_executor" if name == "OpenHands" else None),
    }


def read_external_integration_config() -> dict[str, object]:
    load_dotenv(override=True)
    return {
        "probe_timeout_seconds": int(os.getenv("ORCH_INTEGRATION_PROBE_TIMEOUT_SECONDS", "5")),
        "bindings": [
            _integration_binding(
                name="Open WebUI",
                role="human_entry",
                kind="http",
                base_env="ORCH_OPENWEBUI_BASE_URL",
                status_env="ORCH_OPENWEBUI_STATUS_URL",
                api_key_env="ORCH_OPENWEBUI_API_KEY",
            ),
            _integration_binding(
                name="Appsmith",
                role="control_surface",
                kind="http",
                base_env="ORCH_APPSMITH_BASE_URL",
                status_env="ORCH_APPSMITH_STATUS_URL",
                api_key_env="ORCH_APPSMITH_API_KEY",
            ),
            _integration_binding(
                name="n8n",
                role="automation_orchestrator",
                kind="http",
                base_env="ORCH_N8N_BASE_URL",
                status_env="ORCH_N8N_STATUS_URL",
                api_key_env="ORCH_N8N_API_KEY",
            ),
            _integration_binding(
                name="Dify",
                role="ai_workflow_orchestrator",
                kind="http",
                base_env="ORCH_DIFY_BASE_URL",
                status_env="ORCH_DIFY_STATUS_URL",
                api_key_env="ORCH_DIFY_API_KEY",
            ),
            _integration_binding(
                name="OpenHands",
                role="execution_worker",
                kind="executor",
                base_env="ORCH_OPENHANDS_BASE_URL",
                status_env="ORCH_OPENHANDS_STATUS_URL",
                api_key_env="ORCH_OPENHANDS_API_KEY",
                executor_id_env="ORCH_OPENHANDS_EXECUTOR_ID",
            ),
            {
                "name": "GitHub",
                "role": "source_control_automation",
                "kind": "github",
                "base_url": os.getenv("ORCH_GITHUB_API_URL", os.getenv("GITHUB_API_URL", "https://api.github.com")).strip() or None,
                "status_url": None,
                "api_key_configured": bool(
                    _first_env(
                        "GITHUB_TOKEN",
                        "GH_TOKEN",
                        "ORCH_GITHUB_APP_INSTALLATION_TOKEN",
                        "GITHUB_APP_INSTALLATION_TOKEN",
                        default="",
                    )
                ),
                "executor_id": None,
                "auth_mode": _first_env(
                    "ORCH_GITHUB_AUTH_MODE",
                    "GITHUB_AUTH_MODE",
                    default="auto",
                ),
                "app_id_configured": bool(os.getenv("ORCH_GITHUB_APP_ID", "").strip()),
                "installation_id_configured": bool(os.getenv("ORCH_GITHUB_APP_INSTALLATION_ID", "").strip()),
                "owner": os.getenv("ORCH_GITHUB_APP_OWNER", "").strip() or None,
            },
        ],
    }
