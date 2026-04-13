from __future__ import annotations

import re
from typing import Any

BLOCK_RULES = [
    {
        'id': 'override_instructions',
        'category': 'prompt_injection',
        'severity': 'high',
        'patterns': [
            r'\bignore (all )?(previous|prior|earlier) instructions\b',
            r'\bdisregard (all )?(previous|prior|earlier) instructions\b',
            r'\bbypass (all )?(rules|guardrails|safety|approval)\b',
            r'\boverride (the )?(system|developer|safety|approval) (prompt|instructions|policy)\b',
        ],
    },
    {
        'id': 'prompt_exfiltration',
        'category': 'prompt_exfiltration',
        'severity': 'high',
        'patterns': [
            r'\b(show|reveal|print|dump|expose) (the )?(system prompt|developer prompt|hidden prompt)\b',
            r'\bwhat is (your|the) system prompt\b',
        ],
    },
    {
        'id': 'role_hijack',
        'category': 'role_hijack',
        'severity': 'high',
        'patterns': [
            r'\byou are now (the )?(system|developer|root|admin)\b',
            r'\bpretend to be (the )?(system|developer|root|admin)\b',
        ],
    },
    {
        'id': 'forced_unsafe_tool_use',
        'category': 'tool_manipulation',
        'severity': 'high',
        'patterns': [
            r'\bmust (call|use|run|execute) (the )?(shell|terminal|command|powershell)\b',
            r'\bexecute (shell|powershell|terminal) commands? without approval\b',
            r'\bdo not ask for approval\b',
        ],
    },
]

SANITIZE_RULES = [
    {
        'id': 'suspicious_role_override',
        'category': 'role_hijack',
        'severity': 'medium',
        'patterns': [
            r'\bignore the rules\b',
            r'\bforget the safety policy\b',
            r'\btool override\b',
        ],
    },
]

EXAMPLE_MARKERS = ('example', 'examples', 'for example', '例如', '示例', '样例', 'sample', 'attack')


def _compile(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compiled = []
    for rule in rules:
        compiled.append(
            {
                **rule,
                'compiled_patterns': [re.compile(pattern, re.IGNORECASE) for pattern in rule.get('patterns', [])],
            }
        )
    return compiled


_COMPILED_BLOCK_RULES = _compile(BLOCK_RULES)
_COMPILED_SANITIZE_RULES = _compile(SANITIZE_RULES)


def _is_example_line(line: str) -> bool:
    lowered = line.lower()
    if any(marker in lowered for marker in EXAMPLE_MARKERS):
        return True
    prefix = lowered.split(':', 1)[0].strip()
    return prefix in EXAMPLE_MARKERS


def _iter_live_lines(text: str) -> list[tuple[int, str, bool]]:
    live_lines: list[tuple[int, str, bool]] = []
    in_code_block = False
    for idx, raw_line in enumerate(text.splitlines()):
        stripped = raw_line.strip()
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        live_lines.append((idx, raw_line, _is_example_line(raw_line)))
    return live_lines


def _apply_rule_set(lines: list[tuple[int, str, bool]], rules: list[dict[str, Any]], *, allow_examples: bool) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for line_no, raw_line, is_example in lines:
        if is_example and allow_examples:
            continue
        for rule in rules:
            for pattern in rule['compiled_patterns']:
                if pattern.search(raw_line):
                    matches.append(
                        {
                            'rule_id': rule['id'],
                            'category': rule['category'],
                            'severity': rule['severity'],
                            'line': line_no + 1,
                            'text': raw_line.strip()[:200],
                            'example_context': is_example,
                        }
                    )
                    break
    return matches


def sanitize_prompt_text(text: str, matches: list[dict[str, Any]]) -> str:
    blocked_lines = {item['line'] for item in matches if not item.get('example_context')}
    if not blocked_lines:
        return text
    sanitized_lines = []
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        if idx in blocked_lines:
            sanitized_lines.append('[prompt-guard removed suspicious instruction]')
        else:
            sanitized_lines.append(raw_line)
    sanitized = '\n'.join(sanitized_lines).strip()
    return sanitized or '[prompt-guard removed suspicious instruction]'


def evaluate_prompt_guard(prompt: str, *, goal: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    text = (prompt or '').strip()
    combined = text
    if goal:
        combined = f"{text}\n\nGoal:\n{goal.strip()}"
    lines = _iter_live_lines(combined)
    block_matches = _apply_rule_set(lines, _COMPILED_BLOCK_RULES, allow_examples=True)
    sanitize_matches = _apply_rule_set(lines, _COMPILED_SANITIZE_RULES, allow_examples=False)
    all_matches = block_matches + sanitize_matches

    decision = 'allow'
    risk_level = 'low'
    sanitized_prompt = text
    reasons: list[str] = []

    if block_matches:
        decision = 'block'
        risk_level = 'high'
        sanitized_prompt = sanitize_prompt_text(text, block_matches)
        reasons.append('High-risk prompt injection pattern detected.')
    elif sanitize_matches:
        decision = 'sanitize'
        risk_level = 'medium'
        sanitized_prompt = sanitize_prompt_text(text, sanitize_matches)
        reasons.append('Suspicious prompt content was sanitized before planning.')

    return {
        'decision': decision,
        'risk_level': risk_level,
        'sanitized_prompt': sanitized_prompt,
        'matched_rules': all_matches,
        'reason_summary': '; '.join(reasons) if reasons else 'Prompt accepted.',
        'metadata': metadata or {},
    }
