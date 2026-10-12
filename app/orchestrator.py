
# app/orchestrator.py

import logging
from collections.abc import Callable
from typing import Any

from app.connectors import MockPeopleSystemConnector
from app.models import OnboardingRequest, OnboardingResponse
from app.retry import retry_operation
from app.validation import validate_onboarding_request
from app.workflow_store import WorkflowStore

logger = logging.getLogger(__name__)


class OnboardingOrchestrator:
    def __init__(
        self,
        connector: MockPeopleSystemConnector | None = None,
        store: WorkflowStore | None = None,
    ) -> None:
        self.connector = connector or MockPeopleSystemConnector()
        self.store = (
        store if store is not None else WorkflowStore(":memory:")
         )
    def run(
        self,
        request: OnboardingRequest,
        *,
        resume: bool = False,
    ) -> OnboardingResponse:
        employee_id = request.employee_id
        employee: dict[str, Any] = request.model_dump(mode="json")

        try:
            validate_onboarding_request(request)
        except ValueError as exc:
            return OnboardingResponse(
                employee_id=employee_id,
                status="failed",
                message=str(exc),
            )

        workflow = self.store.get(employee_id)

        if workflow is not None:
            if workflow["employee_data"] != employee:
                return OnboardingResponse(
                    employee_id=employee_id,
                    status="failed",
                    completed_steps=workflow["completed_steps"],
                    failed_step=workflow["failed_step"],
                    message=(
                        "An onboarding workflow already exists for "
                        "this employee ID with different employee data."
                    ),
                )

            if workflow["status"] == "completed":
                return OnboardingResponse(
                    employee_id=employee_id,
                    status="completed",
                    completed_steps=workflow["completed_steps"],
                    failed_step=None,
                    message="Onboarding was already completed.",
                )

            if not resume and workflow["status"] == "failed":
                return OnboardingResponse(
                    employee_id=employee_id,
                    status="failed",
                    completed_steps=workflow["completed_steps"],
                    failed_step=workflow["failed_step"],
                    message=(
                        "A failed workflow exists. Resume it explicitly."
                    ),
                )

            completed_steps = workflow["completed_steps"]
        else:
            self.store.create(employee_id, employee)
            completed_steps = []

        steps: list[
            tuple[str, Callable[[], dict[str, Any]]]
        ] = [
            (
                "create_employee_record",
                lambda: self.connector.create_employee_record(employee),
            ),
            (
                "provision_accounts",
                lambda: self.connector.provision_accounts(employee),
            ),
            (
                "schedule_orientation",
                lambda: self.connector.schedule_orientation(employee),
            ),
            (
                "send_welcome_email",
                lambda: self.connector.send_welcome_email(employee),
            ),
        ]

        for step_name, execute_step in steps:
            if step_name in completed_steps:
                continue

            try:
                retry_operation(
                    execute_step,
                    max_attempts=3,
                    base_delay=0.25,
                )
                completed_steps.append(step_name)

                # Persist progress after each successful step.
                self.store.update(
                    employee_id,
                    status="running",
                    completed_steps=completed_steps,
                )

            except Exception:
                logger.exception(
                    "Onboarding step %s failed for %s",
                    step_name,
                    employee_id,
                )

                message = f"Onboarding failed at step: {step_name}."

                self.store.update(
                    employee_id,
                    status="failed",
                    completed_steps=completed_steps,
                    failed_step=step_name,
                    message=message,
                )

                return OnboardingResponse(
                    employee_id=employee_id,
                    status="failed",
                    completed_steps=completed_steps,
                    failed_step=step_name,
                    message=message,
                )

        message = "Employee onboarding completed successfully."

        self.store.update(
            employee_id,
            status="completed",
            completed_steps=completed_steps,
            message=message,
        )

        return OnboardingResponse(
            employee_id=employee_id,
            status="completed",
            completed_steps=completed_steps,
            message=message,
        )