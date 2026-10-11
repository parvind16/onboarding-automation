
from app.models import (
    EmployeeChangeRequest,
    ChangePropagationResponse,
)


class ChangePropagationService:
    """Mock cross-system validation and safe change propagation."""

    TARGET_SYSTEMS = {
        "department": ("workday", "cohort_tracker"),
        "manager_email": ("workday", "okta_lumos"),
        "start_date": ("workday", "equipment", "cohort_tracker"),
        "work_location": ("workday", "okta_lumos", "equipment"),
    }

    def __init__(self) -> None:
        # Mock records for Ashby and downstream systems.
        self.records: dict[str, dict[str, dict[str, str]]] = {
            "ashby": {},
            "workday": {},
            "okta_lumos": {},
            "equipment": {},
            "cohort_tracker": {},
        }

        # Store completed results so repeated requests are idempotent.
        self.processed_changes: dict[str, tuple[dict, ChangePropagationResponse]] = {}

    def seed_employee(
        self,
        employee_id: str,
        system_values: dict[str, dict[str, str]],
    ) -> None:
        """Load sample employee data into the mock systems."""
        for system, values in system_values.items():
            if system not in self.records:
                raise ValueError(f"Unknown system: {system}")

            self.records[system][employee_id] = values.copy()

    def process_change(
        self,
        change: EmployeeChangeRequest,
    ) -> ChangePropagationResponse:
        """Validate a change before updating downstream systems."""

        payload = change.model_dump(mode="json")

        # Return the original result for an identical repeated request.
        previous = self.processed_changes.get(change.change_id)
        if previous is not None:
            previous_payload, previous_result = previous

            if previous_payload == payload:
                return previous_result.model_copy(deep=True)

            return ChangePropagationResponse(
                change_id=change.change_id,
                employee_id=change.employee_id,
                status="conflict",
                conflicts=[
                    "This change ID has already been used for a different request."
                ],
                message="Change rejected because the change ID was reused.",
            )

        employee_id = change.employee_id
        field_name = change.field_name
        conflicts: list[str] = []

        # Ashby is the source of truth and must already contain the new value.
        source_value = self.records["ashby"].get(employee_id, {}).get(field_name)

        if source_value != change.new_value:
            conflicts.append(
                f"Ashby: expected approved value '{change.new_value}', "
                f"found '{source_value}'."
            )

        targets = self.TARGET_SYSTEMS[field_name]

        # Check every target before changing any target.
        for system in targets:
            current_value = self.records[system].get(employee_id, {}).get(
                field_name
            )

            if current_value != change.old_value:
                conflicts.append(
                    f"{system}: expected '{change.old_value}', "
                    f"found '{current_value}'."
                )

        if conflicts:
            result = ChangePropagationResponse(
                change_id=change.change_id,
                employee_id=employee_id,
                status="conflict",
                conflicts=conflicts,
                message="No downstream systems were updated because validation failed.",
            )
        else:
            for system in targets:
                self.records[system][employee_id][field_name] = change.new_value

            result = ChangePropagationResponse(
                change_id=change.change_id,
                employee_id=employee_id,
                status="propagated",
                updated_systems=list(targets),
                message="Change validated and propagated successfully.",
            )

        self.processed_changes[change.change_id] = (payload, result)
        return result