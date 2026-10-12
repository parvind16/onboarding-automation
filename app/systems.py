# app/systems.py
"""Per-system connectors for change propagation.

Each connector owns:
  * FIELD_MAP   - canonical (Ashby) field name -> that system's native field
  * encode()    - canonical value -> native representation
  * decode()    - native representation -> canonical value

Callers only ever see canonical values, so the propagation service can
compare "what Ashby says" with "what Workday holds" without knowing that
Workday calls department `supervisory_org` or that the equipment vendor
stores a ship-by date rather than a start date.

All systems are in-memory mocks. Real implementations would wrap each
vendor's REST API behind this same interface.
"""

from datetime import date, timedelta

# Equipment (ExpoIT) must ship 7 days before the start date.
EQUIPMENT_LEAD_DAYS = 7


class ConnectorError(Exception):
    """Transient or permanent failure talking to an external system."""


class BaseConnector:
    name: str = ""
    FIELD_MAP: dict[str, str] = {}

    def __init__(self) -> None:
        self._data: dict[str, dict[str, str]] = {}
        # Failure injection for tests and demos.
        self.fail_next_reads = 0
        self.fail_next_writes = 0
        self.always_fail_writes = False

    # ---- capability ---------------------------------------------------

    def supports(self, field: str) -> bool:
        return field in self.FIELD_MAP

    # ---- value translation (override per system) ----------------------

    def encode(self, field: str, value: str) -> str:
        return value

    def decode(self, field: str, native: str) -> str:
        return native

    # ---- data access ---------------------------------------------------

    def seed(self, employee_id: str, canonical_values: dict[str, str]) -> None:
        record = self._data.setdefault(employee_id, {})
        for field, value in canonical_values.items():
            self._require_supported(field)
            record[self.FIELD_MAP[field]] = self.encode(field, value)

    def read(self, employee_id: str, field: str) -> str | None:
        self._require_supported(field)

        if self.fail_next_reads > 0:
            self.fail_next_reads -= 1
            raise ConnectorError(f"{self.name}: read timed out")

        native = self._data.get(employee_id, {}).get(self.FIELD_MAP[field])
        return None if native is None else self.decode(field, native)

    def write(self, employee_id: str, field: str, value: str) -> None:
        self._require_supported(field)

        if self.always_fail_writes:
            raise ConnectorError(f"{self.name}: write rejected (503)")

        if self.fail_next_writes > 0:
            self.fail_next_writes -= 1
            raise ConnectorError(f"{self.name}: write timed out")

        record = self._data.get(employee_id)
        if record is None:
            raise ConnectorError(f"{self.name}: no record for {employee_id}")

        # Idempotent by construction: writing the same value twice is a no-op.
        record[self.FIELD_MAP[field]] = self.encode(field, value)

    def native_record(self, employee_id: str) -> dict[str, str]:
        """Native view of a record, for demos and debugging."""
        return dict(self._data.get(employee_id, {}))

    def _require_supported(self, field: str) -> None:
        if field not in self.FIELD_MAP:
            raise ValueError(f"{self.name} does not own field '{field}'")


class AshbyConnector(BaseConnector):
    """Source of truth. Uses canonical field names."""

    name = "ashby"
    FIELD_MAP = {
        "department": "department",
        "manager_email": "manager_email",
        "start_date": "start_date",
        "work_location": "work_location",
    }


class WorkdayConnector(BaseConnector):
    name = "workday"
    FIELD_MAP = {
        "department": "supervisory_org",
        "manager_email": "manager_email",
        "start_date": "hire_date",
        "work_location": "location",
    }


class OktaLumosConnector(BaseConnector):
    """Identity/access: manager drives approval chains, location drives groups."""

    name = "okta_lumos"
    FIELD_MAP = {
        "manager_email": "manager",
        "work_location": "location_group",
    }

    def encode(self, field: str, value: str) -> str:
        # Okta stores manager as a lower-cased login.
        return value.lower() if field == "manager_email" else value


class EquipmentConnector(BaseConnector):
    """Hardware vendor. Tracks a ship-by date, not a start date."""

    name = "equipment"
    FIELD_MAP = {
        "start_date": "ship_by_date",
        "work_location": "ship_to_region",
    }

    def encode(self, field: str, value: str) -> str:
        if field == "start_date":
            ship_by = date.fromisoformat(value) - timedelta(
                days=EQUIPMENT_LEAD_DAYS
            )
            return ship_by.isoformat()
        return value

    def decode(self, field: str, native: str) -> str:
        if field == "start_date":
            start = date.fromisoformat(native) + timedelta(
                days=EQUIPMENT_LEAD_DAYS
            )
            return start.isoformat()
        return native


class CohortTrackerConnector(BaseConnector):
    name = "cohort_tracker"
    FIELD_MAP = {
        "department": "cohort_dept",
        "start_date": "cohort_start",
    }


def build_default_systems() -> dict[str, BaseConnector]:
    connectors = [
        AshbyConnector(),
        WorkdayConnector(),
        OktaLumosConnector(),
        EquipmentConnector(),
        CohortTrackerConnector(),
    ]
    return {connector.name: connector for connector in connectors}
