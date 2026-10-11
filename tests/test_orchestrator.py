# tests/test_orchestrator.py

from datetime import date, timedelta

from app.connectors import MockPeopleSystemConnector
from app.models import OnboardingRequest
from app.orchestrator import (
    OnboardingOrchestrator,
    retry_operation,
)

def make_request() -> OnboardingRequest:
    """Create valid test employee data."""

    return OnboardingRequest(
        employee_id="EMP001",
        first_name="Rahul",
        last_name="Sharma",
        email="rahul@example.com",
        department="Engineering",
        manager_email="manager@example.com",
        start_date=date.today() + timedelta(days=7),
        equipment_required=True,
    )


def test_successful_onboarding() -> None:
    connector = MockPeopleSystemConnector()
    orchestrator = OnboardingOrchestrator(connector)

    response = orchestrator.run(make_request())

    assert response.status == "completed"
    assert len(response.completed_steps) == 4
    assert response.failed_step is None

    assert "EMP001" in connector.employee_records
    assert "EMP001" in connector.provisioned_accounts
    assert "EMP001" in connector.orientation_bookings
    assert "EMP001" in connector.welcome_emails_sent


def test_rejects_past_start_date() -> None:
    orchestrator = OnboardingOrchestrator()

    request = make_request()
    request.start_date = date.today() - timedelta(days=1)

    response = orchestrator.run(request)

    assert response.status == "failed"
    assert "past" in response.message.lower()
    assert response.completed_steps == []


def test_rejects_same_employee_and_manager_email() -> None:
    orchestrator = OnboardingOrchestrator()

    request = make_request()
    request.manager_email = request.email

    response = orchestrator.run(request)

    assert response.status == "failed"
    assert "must be different" in response.message


def test_stops_when_connector_fails() -> None:
    class FailingConnector(MockPeopleSystemConnector):
        def provision_accounts(
            self, employee: dict
        ) -> dict:
            raise RuntimeError("Identity service unavailable")

    connector = FailingConnector()
    orchestrator = OnboardingOrchestrator(connector)

    response = orchestrator.run(make_request())

    assert response.status == "failed"
    assert response.failed_step == "provision_accounts"
    assert response.completed_steps == [
        "create_employee_record"
    ]

    # Later steps must not execute after the failure.
    assert "EMP001" not in connector.orientation_bookings
    assert "EMP001" not in connector.welcome_emails_sent

def test_duplicate_employee_is_idempotent() -> None:
    connector = MockPeopleSystemConnector()
    orchestrator = OnboardingOrchestrator(connector)

    first_response = orchestrator.run(make_request())
    second_response = orchestrator.run(make_request())

    assert first_response.status == "completed"
    assert second_response.status == "completed"

    assert second_response.completed_steps == [
        "create_employee_record",
        "provision_accounts",
        "schedule_orientation",
        "send_welcome_email",
    ]

    assert second_response.failed_step is None
    assert second_response.message == "Onboarding was already completed."

def test_retry_succeeds_after_transient_failure():
    attempts = 0

    def flaky_operation():
        nonlocal attempts
        attempts += 1

        if attempts < 3:
            raise RuntimeError("Temporary service failure")

        return "success"

    result = retry_operation(
        flaky_operation,
        max_attempts=3,
        base_delay=0,
        sleep=lambda _: None,
    )

    assert result == "success"
    assert attempts == 3    