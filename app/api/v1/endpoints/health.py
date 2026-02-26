"""Health endpoint router (delegates to runtime state)."""
from typing import Any, Dict
from fastapi import APIRouter, Depends
from lumiq.app.api.deps import get_runtime

router = APIRouter()

@router.get('/health')
def health(runtime=Depends(get_runtime)) -> Dict[str, Any]:
    return {
        'ok': True,
        'strategies_running': runtime.orchestrator.list_running_strategies(),
        'alerts_enabled': runtime.alert_system is not None,
        'team_enabled': runtime.team is not None,
    }
