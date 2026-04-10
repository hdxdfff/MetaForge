import json
import re
import subprocess
from pathlib import Path

ROOT = Path(r'D:\codex')
CONFIG_PATH = ROOT / 'METAFORGE_OS_LOCAL_LLM_CONFIG.json'


def run_ps1(script_name: str) -> dict:
    cmd = [
        'powershell',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        str(ROOT / script_name),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig'))


def local_llm_available(config: dict) -> bool:
    runtime = config.get('runtime', {})
    model = config.get('model', {})
    node_path = runtime.get('node_path')
    model_path = model.get('model_path')
    return bool(node_path and model_path and Path(node_path).exists() and Path(model_path).exists())


def build_prompt(self_status: dict, ceo_status: dict, improvement_status: dict) -> str:
    compact = {
        'identity': {
            'name': self_status.get('identity', {}).get('name'),
            'mission': self_status.get('identity', {}).get('mission'),
        },
        'state': self_status.get('state', {}),
        'route_drift_count': ceo_status.get('delivery', {}).get('route_drift_count', 0),
        'target_workspace': ceo_status.get('delivery', {}).get('target_workspace'),
        'active_roots': ceo_status.get('delivery', {}).get('active_task_execution_roots', []),
        'current_priority': ceo_status.get('ceo', {}).get('current_priority'),
        'current_focus': ceo_status.get('ceo', {}).get('current_focus'),
        'should_degrade': ceo_status.get('ceo', {}).get('should_degrade'),
        'recommended_mode': improvement_status.get('recommended_mode'),
        'recommended_targets': improvement_status.get('recommended_targets', []),
        'top_contradiction_hint': improvement_status.get('top_contradiction'),
        'guardrail': improvement_status.get('guardrail'),
    }
    return (
        'Analyze this MetaForge OS summary and return compact JSON only with keys '
        'top_contradiction, priority, next_action, defer, degrade, scale. '
        + json.dumps(compact, ensure_ascii=False)
    )


def build_system_prompt() -> str:
    return (
        'You are the MetaForge OS local status model. '
        'Return valid JSON only. '
        'Use this schema exactly: '
        '{"top_contradiction":"string","priority":"red|orange|yellow|green",'
        '"next_action":"string","defer":["string"],"degrade":true,"scale":false}. '
        'Prefer concise operational recommendations.'
    )


def resolve_cli_js(cli_path: str) -> Path:
    cli = Path(cli_path)
    if cli.suffix.lower() == '.cmd':
        return cli.resolve().parent.parent / 'node-llama-cpp' / 'dist' / 'cli' / 'cli.js'
    return cli.resolve()


def extract_json_from_chat_output(text: str) -> dict:
    match = re.search(r'AI:\s*(\{.*?\})\s*>', text, flags=re.S)
    if match:
        return json.loads(match.group(1))

    brace_match = re.search(r'(\{.*\})', text, flags=re.S)
    if brace_match:
        return json.loads(brace_match.group(1))

    raise ValueError('No JSON payload found in local LLM output')


def try_gpu_mode(cmd_prefix: list[str], gpu_mode: str, timeout_seconds: int) -> dict:
    cmd = cmd_prefix + ['--gpu', gpu_mode]
    completed = subprocess.run(
        cmd,
        input='/exit\n',
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return extract_json_from_chat_output(completed.stdout)


def run_local_llm(config: dict, prompt: str) -> dict:
    runtime = config['runtime']
    model = config['model']
    node_path = runtime['node_path']
    cli_js = resolve_cli_js(runtime['cli_path'])
    cmd_prefix = [
        node_path,
        str(cli_js),
        'chat',
        model['model_path'],
        '--systemPrompt',
        build_system_prompt(),
        '--prompt',
        prompt,
        '--wrapper',
        'qwen',
        '--grammar',
        'json',
        '--noHistory',
        '--contextSize',
        str(min(int(model.get('context_size', 4096)), 2048)),
        '--temperature',
        str(model.get('temperature', 0.1)),
        '--maxTokens',
        str(min(int(model.get('max_tokens', 512)), 160)),
    ]

    preferred_modes = config.get('runtime', {}).get('gpu_modes', ['auto', 'false', 'cuda'])
    errors = []
    timeout_seconds = int(config.get('timeout_seconds', 90))
    for gpu_mode in preferred_modes:
        try:
            payload = try_gpu_mode(cmd_prefix, gpu_mode, timeout_seconds)
            payload['_gpu_mode'] = gpu_mode
            payload['_provider'] = 'node-llama-cpp'
            return payload
        except Exception as exc:
            errors.append(f'{gpu_mode}: {exc}')

    raise RuntimeError(' | '.join(errors))


def structured_fallback(self_status: dict, ceo_status: dict, improvement_status: dict) -> dict:
    contradiction = improvement_status.get('top_contradiction', 'unknown')
    priority = ceo_status.get('ceo', {}).get('current_priority', 'yellow')
    next_action = improvement_status.get('next_action') or ceo_status.get('ceo', {}).get('next_best_action')
    degrade = bool(ceo_status.get('ceo', {}).get('should_degrade', False))
    scale = contradiction == 'throughput_optimization' and not degrade
    defer = []
    if contradiction == 'route_drift':
        defer = ['throughput scaling', 'provider-reuse optimization before routing repair']
    return {
        'mode': 'structured-rules',
        'top_contradiction': contradiction,
        'priority': priority,
        'next_action': next_action,
        'defer': defer,
        'degrade': degrade,
        'scale': scale,
    }


def main() -> None:
    config = load_config()
    self_status = run_ps1('metaforge-self-status.ps1')
    ceo_status = run_ps1('metaforge-ceo-status.ps1')
    improvement_status = run_ps1('metaforge-improvement-status.ps1')

    result = {
        'provider': 'structured-rules',
        'local_llm_ready': False,
        'config_path': str(CONFIG_PATH),
    }

    if local_llm_available(config):
        prompt = build_prompt(self_status, ceo_status, improvement_status)
        try:
            llm_result = run_local_llm(config, prompt)
            result['provider'] = 'local-llm'
            result['local_llm_ready'] = True
            result['summary'] = llm_result
        except Exception as exc:
            result['provider'] = 'structured-rules'
            result['local_llm_ready'] = False
            result['llm_error'] = str(exc)
            result['summary'] = structured_fallback(self_status, ceo_status, improvement_status)
    else:
        result['summary'] = structured_fallback(self_status, ceo_status, improvement_status)

    result['inputs'] = {
        'self': self_status,
        'ceo': ceo_status,
        'improvement': improvement_status,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
