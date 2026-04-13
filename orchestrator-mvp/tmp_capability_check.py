import json
from app.orchestrator import Orchestrator
orch = Orchestrator()
policy = orch._policy.model_dump(mode='json')
print(json.dumps({
    'capability_count': len(orch._capabilities),
    'policy_version': policy.get('version'),
    'has_dev_test_loop': 'development_test_loop' in policy,
    'capability_summary': orch._capabilities[0].get('summary') if orch._capabilities else None,
}, ensure_ascii=False, indent=2))
