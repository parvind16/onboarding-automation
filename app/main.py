
import os

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.models import OnboardingRequest, OnboardingResponse
from app.orchestrator import OnboardingOrchestrator
from app.workflow_store import WorkflowStore
from app.change_propagation import ChangePropagationService
from app.change_store import ChangeStore
from app.classifier import get_default_classifier
from app.models import EmployeeChangeRequest, ChangePropagationResponse

app = FastAPI(
    title="Employee Onboarding Automation",
    description="API for automating employee onboarding workflows.",
    version="1.0.0",
)

# Durable idempotency keys + audit trail. Claude classifies conflicts when
# ANTHROPIC_API_KEY is set; deterministic rules otherwise.
change_service = ChangePropagationService(
    store=ChangeStore(os.getenv("CHANGE_DB", "changes.db")),
    classifier=get_default_classifier(),
)

# Mock systems are in-memory and reseeded on every start. Ashby already holds
# the approved values; downstream systems still hold the old ones.
change_service.seed_employee(
    "EMP-DEMO-01",
    {
        "ashby": {
            "department": "Product",
            "manager_email": "new.manager@example.com",
            "start_date": "2026-11-16",
            "work_location": "Austin",
        },
        "workday": {
            "department": "Engineering",
            "manager_email": "old.manager@example.com",
            "start_date": "2026-11-09",
            "work_location": "Denver",
        },
        "okta_lumos": {
            "manager_email": "old.manager@example.com",
            "work_location": "Denver",
        },
        "equipment": {
            "start_date": "2026-11-09",
            "work_location": "Denver",
        },
        "cohort_tracker": {
            "department": "Engineering",
            "start_date": "2026-11-09",
        },
    },
)

# Shared orchestrator with persistent SQLite workflow storage.
connector_orchestrator = OnboardingOrchestrator(
    store=WorkflowStore("onboarding.db")
)


@app.get("/health", summary="Health Check")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.post(
    "/onboarding",
    response_model=OnboardingResponse,
    summary="Start Onboarding",
)
def create_onboarding(
    request: OnboardingRequest,
) -> OnboardingResponse:
    try:
        return connector_orchestrator.run(request)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(),
        ) from exc


@app.post(
    "/onboarding/{employee_id}/resume",
    response_model=OnboardingResponse,
    summary="Resume Onboarding",
)
def resume_onboarding(
    employee_id: str,
) -> OnboardingResponse:
    workflow = connector_orchestrator.store.get(employee_id)

    if workflow is None:
        raise HTTPException(
            status_code=404,
            detail="Onboarding workflow not found",
        )

    request = OnboardingRequest.model_validate(
        workflow["employee_data"]
    )

    return connector_orchestrator.run(request, resume=True)

@app.post(
    "/changes/propagate",
    response_model=ChangePropagationResponse,
    summary="Validate and Propagate Employee Change",
)
def propagate_employee_change(
    request: EmployeeChangeRequest,
) -> ChangePropagationResponse:
    return change_service.process_change(request)


@app.get(
    "/changes/{change_id}/audit",
    summary="Audit trail for a change",
)
def change_audit_trail(change_id: str) -> list[dict]:
    trail = change_service.store.audit_trail(change_id)
    if not trail:
        raise HTTPException(status_code=404, detail="Change not found")
    return trail
