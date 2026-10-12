import pytest
from pydantic import ValidationError

from app.change_store import ChangeStore
from app.systems import ConnectorError
from tests.conftest import EMP, make_change, make_service


def read(service, system, field):
    return service.systems[system].read(EMP, field)


# ---- happy path and field mapping ----------------------------------------


def test_successful_change_propagation(service, change_request):
    result = service.process_change(change_request)

    assert result.status == "propagated"
    assert set(result.updated_systems) == {"workday", "cohort_tracker"}
    assert read(service, "workday", "department") == "Product"
    assert read(service, "cohort_tracker", "department") == "Product"


def test_targets_are_derived_from_each_systems_field_ownership(service):
    assert service.targets_for("start_date") == [
        "workday",
        "equipment",
        "cohort_tracker",
    ]
    assert service.targets_for("manager_email") == ["workday", "okta_lumos"]


def test_native_field_names_are_used_per_system(service, change_request):
    service.process_change(change_request)

    assert service.systems["workday"].native_record(EMP)["supervisory_org"] == "Product"
    assert service.systems["cohort_tracker"].native_record(EMP)["cohort_dept"] == "Product"


def test_equipment_stores_ship_by_date_seven_days_before_start(service):
    result = service.process_change(make_change("start_date"))

    assert result.status == "propagated"
    equipment = service.systems["equipment"]
    assert equipment.native_record(EMP)["ship_by_date"] == "2026-11-09"
    # Callers still see the canonical start date.
    assert read(service, "equipment", "start_date") == "2026-11-16"
    assert read(service, "workday", "start_date") == "2026-11-16"


def test_manager_email_comparison_ignores_case_for_okta(service):
    # Ashby has mixed case; Okta stores lower-case.
    result = service.process_change(make_change("manager_email"))

    assert result.status == "propagated"
    assert set(result.updated_systems) == {"workday", "okta_lumos"}


# ---- validation and conflicts --------------------------------------------


def test_conflict_prevents_all_updates(service, change_request):
    service.systems["workday"].seed(EMP, {"department": "Finance"})

    result = service.process_change(change_request)

    assert result.status == "conflict"
    assert result.conflicts
    assert read(service, "workday", "department") == "Finance"
    assert read(service, "cohort_tracker", "department") == "Engineering"


def test_source_not_updated_is_classified_and_not_escalated(service, change_request):
    service.systems["ashby"].seed(EMP, {"department": "Sales"})

    result = service.process_change(change_request)

    assert result.status == "conflict"
    assert result.classification.category == "source_not_updated"
    assert result.classification.recommended_action == "retry_after_source_sync"
    assert result.escalated is False
    assert service.notifier.messages == []


def test_missing_target_record_escalates_to_slack(service, change_request):
    service.systems["cohort_tracker"]._data.pop(EMP)

    result = service.process_change(change_request)

    assert result.classification.category == "missing_target_record"
    assert result.escalated is True
    assert len(service.notifier.messages) == 1


def test_slack_message_never_contains_field_values(service, change_request):
    service.systems["cohort_tracker"]._data.pop(EMP)
    service.process_change(change_request)

    _, text = service.notifier.messages[0]
    assert "Engineering" not in text and "Product" not in text
    assert "CHG-TEST-001" in text


def test_identical_old_and_new_value_is_rejected():
    with pytest.raises(ValidationError):
        make_change(old_value="Product")


def test_start_date_must_be_iso_date():
    with pytest.raises(ValidationError):
        make_change("start_date", new_value="16/11/2026")


def test_manager_email_must_be_an_email():
    with pytest.raises(ValidationError):
        make_change("manager_email", new_value="not-an-email")


# ---- idempotency and durability ------------------------------------------


def test_duplicate_request_is_idempotent(service, change_request):
    first = service.process_change(change_request)
    second = service.process_change(change_request)

    assert first.status == second.status == "propagated"
    assert second.updated_systems == first.updated_systems
    assert read(service, "workday", "department") == "Product"
    events = [e["event"] for e in service.store.audit_trail("CHG-TEST-001")]
    assert events.count("write_applied") == 2  # not 4: replay did not rewrite
    assert "replayed_stored_result" in events


def test_reusing_change_id_with_different_request_is_rejected(service, change_request):
    service.process_change(change_request)

    result = service.process_change(
        change_request.model_copy(update={"new_value": "Finance"})
    )

    assert result.status == "conflict"
    assert any("already been used" in item for item in result.conflicts)
    assert read(service, "workday", "department") == "Product"


def test_idempotency_survives_a_restart(tmp_path, change_request):
    db = str(tmp_path / "changes.db")
    first = make_service(store=ChangeStore(db)).process_change(change_request)

    # "Restart": brand-new service and connectors, same database file.
    restarted = make_service(store=ChangeStore(db))
    replay = restarted.process_change(change_request)

    assert replay == first
    # Replay came from the store; the fresh mock systems were never touched.
    assert read(restarted, "workday", "department") == "Engineering"


def test_unfinished_change_is_resumed_after_a_crash(service, change_request):
    # Simulate a crash: change recorded, Workday already updated, rest not.
    service.store.begin("CHG-TEST-001", change_request.model_dump(mode="json"))
    service.systems["workday"].seed(EMP, {"department": "Product"})

    result = service.process_change(change_request)

    assert result.status == "propagated"
    assert read(service, "cohort_tracker", "department") == "Product"
    events = [e["event"] for e in service.store.audit_trail("CHG-TEST-001")]
    assert "resuming_unfinished_change" in events
    assert events.count("write_applied") == 1  # Workday was not rewritten


def test_purge_removes_only_old_finished_keys(service, change_request):
    service.process_change(change_request)
    assert service.store.purge_older_than(days=30) == 0

    with service.store._session() as connection:
        connection.execute(
            "UPDATE changes SET updated_at = '2020-01-01T00:00:00+00:00'"
        )
    assert service.store.purge_older_than(days=30) == 1
    assert service.store.get("CHG-TEST-001") is None


# ---- failure handling -----------------------------------------------------


def test_transient_write_failures_are_retried(service, change_request):
    service.systems["workday"].fail_next_writes = 2

    result = service.process_change(change_request)

    assert result.status == "propagated"
    assert read(service, "workday", "department") == "Product"


def test_exhausted_retries_roll_back_earlier_writes(service):
    service.systems["equipment"].always_fail_writes = True

    result = service.process_change(make_change("start_date"))

    assert result.status == "failed"
    assert result.updated_systems == []
    assert result.escalated is True
    # Workday (written before equipment) was restored.
    assert read(service, "workday", "start_date") == "2026-11-09"
    assert read(service, "cohort_tracker", "start_date") == "2026-11-09"
    events = [e["event"] for e in service.store.audit_trail("CHG-TEST-001")]
    assert "write_rolled_back" in events


def test_failed_rollback_is_reported_as_inconsistent(service):
    workday = service.systems["workday"]
    original_write = workday.write
    calls = {"n": 0}

    def write_once_then_fail(employee_id, field, value):
        calls["n"] += 1
        if calls["n"] > 1:
            raise ConnectorError("workday: down")
        original_write(employee_id, field, value)

    workday.write = write_once_then_fail
    service.systems["equipment"].always_fail_writes = True

    result = service.process_change(make_change("start_date"))

    assert result.status == "failed"
    assert result.updated_systems == ["workday"]  # still holds the new value
    assert "Manual reconciliation" in result.message
    assert "INCONSISTENT" in service.notifier.messages[0][1]


def test_read_failure_during_validation_writes_nothing(service, change_request):
    service.systems["workday"].fail_next_reads = 10  # outlasts the retries

    result = service.process_change(change_request)

    assert result.status == "failed"
    assert result.escalated is True
    assert read(service, "cohort_tracker", "department") == "Engineering"


def test_audit_trail_records_the_full_story(service, change_request):
    service.process_change(change_request)

    events = [e["event"] for e in service.store.audit_trail("CHG-TEST-001")]
    assert events == [
        "received",
        "validated",
        "write_applied",
        "write_applied",
        "propagated",
    ]
