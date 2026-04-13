from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.security_write import guarded_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
RECORDS = DATA / 'approved_patch_records.json'
HANDOFF = DATA / 'self_improvement_handoff.json'
PATCH_SUBMISSIONS = DATA / 'patch_submissions.json'


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    guarded_write_json(
        path,
        payload,
        actor='approve_self_patch',
        purpose='record approved self-improvement patch',
        allow_core_write=True,
    )


def find_handoff_candidate(candidate_id: str) -> dict[str, Any] | None:
    handoff = load_json(HANDOFF, {'items': []})
    return next((entry for entry in handoff.get('items', []) if entry.get('candidate_id') == candidate_id or entry.get('patch_id') == candidate_id), None)


def find_patch_submission(candidate_or_patch: str) -> dict[str, Any] | None:
    payload = load_json(PATCH_SUBMISSIONS, {'submissions': []})
    node_key = f'self_improvement::{candidate_or_patch}'
    for item in payload.get('submissions', []):
        if item.get('patch_id') == candidate_or_patch:
            return item
        if item.get('node_id') == node_key:
            return item
    return None


def infer_candidate_id(submission: dict[str, Any], fallback: str) -> str:
    node_id = str(submission.get('node_id') or '')
    if node_id.startswith('self_improvement::'):
        return node_id.split('self_improvement::', 1)[1]
    return fallback


def infer_target_files(submission: dict[str, Any]) -> list[str]:
    files = []
    for module in submission.get('module_focus') or []:
        files.append(f'{module.replace(".", "/")}.py')
    return files




def python_executable() -> Path:
    embedded = ROOT.parent / 'tools' / 'python311-embed' / 'python.exe'
    if embedded.exists():
        return embedded
    return Path(sys.executable)


def continue_self_patch_loop() -> dict[str, Any]:
    command = [str(python_executable()), str(ROOT / 'tools' / 'self_patch_loop.py')]
    completed = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    stdout_lines = completed.stdout.strip().splitlines()
    stderr_lines = completed.stderr.strip().splitlines()
    payload: dict[str, Any] = {
        'command': command,
        'returncode': completed.returncode,
        'stdout_tail': stdout_lines[-5:],
        'stderr_tail': stderr_lines[-5:],
    }
    if stdout_lines:
        try:
            payload['result'] = json.loads(stdout_lines[-1])
        except json.JSONDecodeError:
            pass
    return payload

def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print('usage: approve_self_patch.py <candidate_id|patch_id> <reviewer> [reason]')
        return 1
    candidate_or_patch = argv[1].strip()
    reviewer = argv[2].strip()
    reason = ' '.join(argv[3:]).strip() or 'approved for bounded self-improvement merge'

    item = find_handoff_candidate(candidate_or_patch)
    submission = find_patch_submission(candidate_or_patch)
    if item is None and submission is None:
        print(json.dumps({'status': 'error', 'reason': 'candidate-or-patch-not-found', 'value': candidate_or_patch}, ensure_ascii=False))
        return 2

    candidate_id = item.get('candidate_id') if item else infer_candidate_id(submission, candidate_or_patch)
    patch_id = item.get('patch_id') if item else submission.get('patch_id')
    target_files = item.get('target_files', []) if item else infer_target_files(submission)
    tests_run = item.get('tests_run', []) if item else ['compileall-tools', 'verification-refresh']
    rollback_note = item.get('rollback_note') if item else 'Revert logical patch record and restore previous approved asset if post-merge verification fails.'

    payload = load_json(RECORDS, {'updated_at': utc_iso(), 'records': []})
    records = [entry for entry in payload.get('records', []) if entry.get('candidate_id') != candidate_id and entry.get('patch_id') != patch_id]
    record = {
        'candidate_id': candidate_id,
        'patch_id': patch_id,
        'reviewer': reviewer,
        'reason': reason,
        'target_files': target_files,
        'validation': tests_run,
        'rollback_note': rollback_note,
        'status': 'approved',
        'approved_at': utc_iso(),
    }
    records.append(record)
    payload['updated_at'] = utc_iso()
    payload['records'] = records
    save_json(RECORDS, payload)
    continuation = continue_self_patch_loop()
    status = 'continued' if continuation.get('returncode') == 0 else 'approved'
    print(json.dumps({
        'status': status,
        'candidate_id': candidate_id,
        'patch_id': patch_id,
        'continuation': continuation,
    }, ensure_ascii=False))
    return 0 if continuation.get('returncode') == 0 else 3


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))

