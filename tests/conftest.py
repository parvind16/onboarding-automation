import pytest

from app.change_propagation import ChangePropagationService
from app.models import EmployeeChangeRequest
from app.notifier import MockSlackNotifier

EMP = "EMP-DEMO-01"

SEED = {
    "ashby": {
        "department": "Product",
        "manager_email": "New.Manager@example.com",
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
    "equipment": {"start_date": "2026-11-09", "work_location": "Denver"},
    "cohort_tracker": {"department": "Engineering", "start_date": "2026-11-09"},
}


def make_service(**kwargs) -> ChangePropagationService:
    kwargs.setdefault("sleep", lambda _: None)
    kwargs.setdefault("notifier", MockSlackNotifier())
    service = ChangePropagationService(**kwargs)
    service.seed_employee(EMP, SEED)
    return service


def make_change(field_name="department", change_id="CHG-TEST-001", **overrides):
    values = {
        "department": ("Engineering", "Product"),
        "manager_email": ("old.manager@example.com", "New.Manager@example.com"),
        "start_date": ("2026-11-09", "2026-11-16"),
        "work_location": ("Denver", "Austin"),
    }
    old, new = values[field_name]
    data = dict(
        change_id=change_id,
        employee_id=EMP,
        source_system="ashby",
        field_name=field_name,
        old_value=old,
        new_value=new,
        requested_by="hr@example.com",
    )
    data.update(overrides)
    return EmployeeChangeRequest(**data)


@pytest.fixture
def service():
    return make_service()


@pytest.fixture
def change_request():
    return make_change()
