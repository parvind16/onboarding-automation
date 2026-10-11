
import pytest

from app.change_propagation import ChangePropagationService
from app.models import EmployeeChangeRequest


@pytest.fixture
def service():
    service = ChangePropagationService()
    service.seed_employee(
        "EMP-DEMO-01",
        {
            "ashby": {"department": "Product"},
            "workday": {"department": "Engineering"},
            "cohort_tracker": {"department": "Engineering"},
        },
    )
    return service


@pytest.fixture
def change_request():
    return EmployeeChangeRequest(
        change_id="CHG-TEST-001",
        employee_id="EMP-DEMO-01",
        source_system="ashby",
        field_name="department",
        old_value="Engineering",
        new_value="Product",
        requested_by="hr@example.com",
    )


def test_successful_change_propagation(service, change_request):
    result = service.process_change(change_request)

    assert result.status == "propagated"
    assert set(result.updated_systems) == {"workday", "cohort_tracker"}
    assert service.records["workday"]["EMP-DEMO-01"]["department"] == "Product"
    assert service.records["cohort_tracker"]["EMP-DEMO-01"]["department"] == "Product"


def test_conflict_prevents_all_updates(service, change_request):
    # Workday has an unexpected value.
    service.records["workday"]["EMP-DEMO-01"]["department"] = "Finance"

    result = service.process_change(change_request)

    assert result.status == "conflict"
    assert result.conflicts
    assert service.records["workday"]["EMP-DEMO-01"]["department"] == "Finance"
    assert (
        service.records["cohort_tracker"]["EMP-DEMO-01"]["department"]
        == "Engineering"
    )


def test_duplicate_request_is_idempotent(service, change_request):
    first = service.process_change(change_request)
    second = service.process_change(change_request)

    assert first.status == "propagated"
    assert second.status == "propagated"
    assert second.updated_systems == first.updated_systems
    assert service.records["workday"]["EMP-DEMO-01"]["department"] == "Product"


def test_reusing_change_id_with_different_request_is_rejected(
    service, change_request
):
    service.process_change(change_request)

    changed_request = change_request.model_copy(
        update={"new_value": "Finance"}
    )
    result = service.process_change(changed_request)

    assert result.status == "conflict"
    assert any("already been used" in item for item in result.conflicts)
    assert service.records["workday"]["EMP-DEMO-01"]["department"] == "Product"