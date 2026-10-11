# app/connectors.py

from typing import Any


class MockPeopleSystemConnector:
    """Simulates integrations with company onboarding systems."""

    def __init__(self) -> None:
        self.employee_records: dict[str, dict[str, Any]] = {}
        self.provisioned_accounts: set[str] = set()
        self.orientation_bookings: set[str] = set()
        self.welcome_emails_sent: set[str] = set()

    def create_employee_record(
        self, employee: dict[str, Any]
    ) -> dict[str, Any]:
        employee_id = employee["employee_id"]

        if employee_id in self.employee_records:
            raise ValueError(
                f"Employee {employee_id} already exists"
            )

        self.employee_records[employee_id] = employee.copy()

        return {
            "employee_id": employee_id,
            "record_created": True,
        }

    def provision_accounts(
        self, employee: dict[str, Any]
    ) -> dict[str, Any]:
        employee_id = employee["employee_id"]

        self.provisioned_accounts.add(employee_id)

        return {
            "employee_id": employee_id,
            "accounts_provisioned": True,
        }

    def schedule_orientation(
        self, employee: dict[str, Any]
    ) -> dict[str, Any]:
        employee_id = employee["employee_id"]

        self.orientation_bookings.add(employee_id)

        return {
            "employee_id": employee_id,
            "orientation_scheduled": True,
        }

    def send_welcome_email(
        self, employee: dict[str, Any]
    ) -> dict[str, Any]:
        employee_id = employee["employee_id"]

        self.welcome_emails_sent.add(employee_id)

        return {
            "employee_id": employee_id,
            "email_sent": True,
            "recipient": employee["email"],
        }