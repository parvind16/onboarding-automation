
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

    if request.work_location is not None:
        if not request.work_location.strip():
            raise ValueError("Work location cannot be blank.")

    if request.shipping_address is not None:
        if not request.shipping_address.strip():
            raise ValueError("Shipping address cannot be blank.")