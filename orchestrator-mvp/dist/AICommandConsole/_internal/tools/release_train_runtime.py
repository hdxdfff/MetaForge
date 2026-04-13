from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.artifact_audit import validate_release_payload
from tools.io_utils import atomic_write_json

DATA = ROOT / "data"

RELEASES = DATA / "release_records.json"
OUT = DATA / "release_train_runtime.json"
STALE_RELEASE_HOURS = 24


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _release_is_stale(item: dict[str, Any], *, hours: int = STALE_RELEASE_HOURS) -> bool:
    ts = _parse_utc(item.get("updated_at") or item.get("created_at"))
    if ts is None:
        return False
    return datetime.now(timezone.utc) - ts > timedelta(hours=hours)


def run_release_train(
    *,
    runtime_ok: bool,
    verification_ok: bool,
    control_ok: bool,
    blocked_patch_count: int,
    experimental_ok: bool | None = None,
) -> dict[str, Any]:
    releases = _load_json(RELEASES, [])
    promoted: list[str] = []
    released: list[str] = []
    experimental_promoted: list[str] = []
    invalid_candidates: list[str] = []
    stale_invalid_candidates: list[str] = []
    archived_stale_candidates: list[str] = []
    experimental_ok = bool(verification_ok and runtime_ok) if experimental_ok is None else bool(experimental_ok)

    audited = []
    for item in releases:
        evidence = validate_release_payload(item.get('repo_path'), item.get('artifacts') or [])
        if item.get('status') in {'prepared', 'candidate', 'ready'} and not evidence.get('passed') and _release_is_stale(item):
            item['status'] = 'archived'
            item['archived_at'] = _utc()
            item['archived_reason'] = 'stale-invalid-artifacts'
            item['notes'] = ((item.get('notes') or '') + ' Archived after stale release candidate failed artifact validation.').strip()
            item['updated_at'] = _utc()
            archived_stale_candidates.append(item.get('id'))
        audited.append((item, evidence))
        if item.get('status') in {'prepared', 'candidate', 'ready'} and not evidence.get('passed'):
            invalid_candidates.append(item.get('id'))
        elif item.get('status') == 'archived' and item.get('archived_reason') == 'stale-invalid-artifacts':
            stale_invalid_candidates.append(item.get('id'))

    artifact_release_ok = len(invalid_candidates) == 0

    if blocked_patch_count == 0 and runtime_ok and verification_ok and control_ok and artifact_release_ok:
        for item, evidence in audited:
            if item.get('status') == 'prepared' and evidence.get('passed'):
                item['status'] = 'candidate'
                item['notes'] = ((item.get('notes') or '') + ' Promoted to candidate by mainline release train runtime.').strip()
                item['updated_at'] = _utc()
                promoted.append(item.get('id'))
        for item, evidence in audited:
            if item.get('status') == 'candidate' and evidence.get('passed'):
                item['status'] = 'ready'
                item['notes'] = ((item.get('notes') or '') + ' Promoted to ready by mainline release train runtime.').strip()
                item['updated_at'] = _utc()
                released.append(item.get('id'))
                break
    elif blocked_patch_count == 0 and experimental_ok and artifact_release_ok:
        for item, evidence in audited:
            if item.get('status') == 'prepared' and evidence.get('passed'):
                notes = item.get('notes') or ''
                if 'experimental release train' in notes:
                    continue
                item['notes'] = (notes + ' Prepared for experimental release train while mainline gates are constrained.').strip()
                item['updated_at'] = _utc()
                experimental_promoted.append(item.get('id'))
                break

    _save_json(RELEASES, releases)
    payload = {
        'updated_at': _utc(),
        'runtime_ok': runtime_ok,
        'verification_ok': verification_ok,
        'control_ok': control_ok,
        'artifact_release_ok': artifact_release_ok,
        'invalid_candidates': invalid_candidates,
        'stale_invalid_candidates': stale_invalid_candidates,
        'archived_stale_candidates': archived_stale_candidates,
        'experimental_ok': experimental_ok,
        'blocked_patch_count': blocked_patch_count,
        'promoted_to_candidate': promoted,
        'promoted_to_ready': released,
        'experimental_promoted': experimental_promoted,
        'status': 'advanced' if promoted or released or experimental_promoted or archived_stale_candidates else 'idle',
        'ready_count': sum(1 for item in releases if item.get('status') == 'ready'),
        'candidate_count': sum(1 for item in releases if item.get('status') == 'candidate'),
        'archived_count': sum(1 for item in releases if item.get('status') == 'archived'),
    }
    _save_json(OUT, payload)
    return payload

if __name__ == "__main__":
    print(json.dumps(run_release_train(runtime_ok=False, verification_ok=False, control_ok=False, blocked_patch_count=0), ensure_ascii=False, indent=2))


