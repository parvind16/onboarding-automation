
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.models import OnboardingRequest, OnboardingResponse
from app.orchestrator import OnboardingOrchestrator
from app.workflow_store import WorkflowStore

app = FastAPI(
    title="Employee Onboarding Automation",
    description="API for automating employee onboarding workflows.",
    version="1.0.0",
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