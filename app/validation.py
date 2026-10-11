# app/validation.py

from datetime import date

from app.models import OnboardingRequest


def validate_onboarding_request(
    request: OnboardingRequest,
) -> None:
    """Validate business rules for employee onboarding."""

    if request.start_date < date.today():
        raise ValueError("Start date cannot be in the past.")

    if request.email.lower() == request.manager_email.lower():
        raise ValueError(
            "Employee email and manager email must be different."
        )

    if not request.department.strip():
        raise ValueError("Department cannot be empty.")