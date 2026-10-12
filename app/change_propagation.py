# app/change_propagation.py

import logging
import threading
import time
from collections.abc import Callable

from app.change_store import ChangeStore
from app.classifier import (
    ConflictClassifier,
    RuleBasedClassifier,
    apply_guardrails,
)
from app.models import (
    ChangePropagationResponse,
    Conflict,
    ConflictClassification,
    EmployeeChangeRequest,
)
from app.notifier import MockSlackNotifier, Notifier
from app.retry import retry_operation
from app.systems import BaseConnector, ConnectorError, build_default_systems

logger = logging.getLogger(__name__)

SOURCE_SYSTEM = "ashby"
ESCALATION_CHANNEL = "#people-tech-alerts"


class ChangePropagationService:
    """Validate a change across systems, then propagate it safely.

    Flow (see docs/SYSTEMS_MAP.md):
      1. Idempotency check against the durable ChangeStore.
      2. Validate: Ashby holds the approved value; every target holds the
         expected old value (or already the new one, which makes re-runs safe).
      3. Any disagreement -> no writes. Claude (or rules) triages the
         conflict; humans are paged in Slack when needed.
      4. Otherwise write each target with bounded retries. If a write still
         fails, compensate by restoring the targets already written.
    """

    def __init__(
        self,
        systems: dict[str, BaseConnector] | None = None,
        store: ChangeStore | None = None,
        classifier: ConflictClassifier | None = None,
        notifier: Notifier | None = None,
        *,
        max_attempts: int = 3,
        base_delay: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.systems = systems or build_default_systems()
        self.store = store or ChangeStore(":memory:")
        self.classifier = classifier or RuleBasedClassifier()
        self.notifier = notifier or MockSlackNotifier()
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self._sleep = sleep
        self._lock = threading.Lock()

    # ---- setup ----------------------------------------------------------

    def seed_employee(
        self,
        employee_id: str,
        system_values: dict[str, dict[str, str]],
    ) -> None:
        """Load sample canonical values into the mock systems."""
        for system, values in system_values.items():
            if system not in self.systems:
                raise ValueError(f"Unknown system: {system}")
            self.systems[system].seed(employee_id, values)

    def targets_for(self, field_name: str) -> list[str]:
        """Downstream systems that own ``field_name`` (derived, not hardcoded)."""
        return [
            name
            for name, connector in self.systems.items()
            if name != SOURCE_SYSTEM and connector.supports(field_name)
        ]

    # ---- public entry point --------------------------------------------

    def process_change(
        self, change: EmployeeChangeRequest
    ) -> ChangePropagationResponse:
        payload = change.model_dump(mode="json")

        # One change at a time keeps check-then-write consistent in-process.
        # In production this becomes a per-employee lock / queue partition.
        with self._lock:
            existing = self.store.get(change.change_id)

            if existing is not None:
                if existing["payload"] != payload:
                    self.store.audit(change.change_id, "id_reuse_rejected")
                    return ChangePropagationResponse(
                        change_id=change.change_id,
                        employee_id=change.employee_id,
                        status="conflict",
                        conflicts=[
                            "This change ID has already been used for a "
                            "different request."
                        ],
                        message="Change rejected because the change ID was reused.",
                    )

                if existing["status"] == "done":
                    self.store.audit(change.change_id, "replayed_stored_result")
                    return ChangePropagationResponse.model_validate(
                        existing["result"]
                    )

                # Same payload, never finished: a previous run crashed.
                self.store.audit(change.change_id, "resuming_unfinished_change")
            else:
                self.store.begin(change.change_id, payload)
                self.store.audit(change.change_id, "received", payload)

            result = self._execute(change)
            self.store.complete(
                change.change_id, result.model_dump(mode="json")
            )
            return result

    # ---- internals -------------------------------------------------------

    def _retry(self, operation: Callable[[], object]):
        return retry_operation(
            operation,
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
            sleep=self._sleep,
            retry_on=(ConnectorError,),
        )

    @staticmethod
    def _same(field_name: str, a: str | None, b: str | None) -> bool:
        if a is None or b is None:
            return a == b
        if field_name == "manager_email":
            return a.casefold() == b.casefold()
        return a == b

    def _validate(self, change: EmployeeChangeRequest) -> list[Conflict]:
        """Read-only cross-system check. Raises ConnectorError if a read
        still fails after bounded retries."""
        field = change.field_name
        employee_id = change.employee_id
        conflicts: list[Conflict] = []

        source = self.systems[SOURCE_SYSTEM]
        source_value = self._retry(lambda: source.read(employee_id, field))
        if not self._same(field, source_value, change.new_value):
            conflicts.append(
                Conflict(
                    system=SOURCE_SYSTEM,
                    expected=change.new_value,
                    found=source_value,
                )
            )

        for name in self.targets_for(field):
            connector = self.systems[name]
            current = self._retry(
                lambda c=connector: c.read(employee_id, field)
            )
            # Already-new is acceptable: it makes re-running a half-finished
            # change safe instead of a spurious conflict.
            if not (
                self._same(field, current, change.old_value)
                or self._same(field, current, change.new_value)
            ):
                conflicts.append(
                    Conflict(system=name, expected=change.old_value, found=current)
                )

        return conflicts

    def _execute(
        self, change: EmployeeChangeRequest
    ) -> ChangePropagationResponse:
        cid = change.change_id
        field = change.field_name
        employee_id = change.employee_id
        targets = self.targets_for(field)

        # ---- 1. validate (no writes) ----
        try:
            conflicts = self._validate(change)
        except ConnectorError as exc:
            self.store.audit(cid, "validation_read_failed", {"error": str(exc)})
            escalated = self._escalate(
                change, f"could not read systems during validation ({exc})"
            )
            return ChangePropagationResponse(
                change_id=cid,
                employee_id=employee_id,
                status="failed",
                escalated=escalated,
                message="Validation could not complete; no systems were updated.",
            )

        if conflicts:
            return self._conflict_result(change, conflicts)

        self.store.audit(cid, "validated", {"targets": targets})

        # ---- 2. write with compensation ----
        applied: list[str] = []
        for name in targets:
            connector = self.systems[name]
            try:
                current = self._retry(
                    lambda c=connector: c.read(employee_id, field)
                )
                already = self._same(field, current, change.new_value)
                if not already:
                    self._retry(
                        lambda c=connector: c.write(
                            employee_id, field, change.new_value
                        )
                    )
                    applied.append(name)
                    self.store.audit(cid, "write_applied", {"system": name})
            except ConnectorError as exc:
                self.store.audit(
                    cid, "write_failed", {"system": name, "error": str(exc)}
                )
                return self._failed_with_rollback(change, name, applied, exc)

        self.store.audit(cid, "propagated", {"updated_systems": targets})
        return ChangePropagationResponse(
            change_id=cid,
            employee_id=employee_id,
            status="propagated",
            updated_systems=targets,
            message="Change validated and propagated successfully.",
        )

    def _conflict_result(
        self, change: EmployeeChangeRequest, conflicts: list[Conflict]
    ) -> ChangePropagationResponse:
        cid = change.change_id
        self.store.audit(
            cid, "conflict_detected", {"conflicts": [c.render() for c in conflicts]}
        )

        classification = self._classify(change, conflicts)
        self.store.audit(cid, "classified", classification.model_dump())

        escalated = False
        if classification.recommended_action == "escalate_to_human":
            # Category only: free-text rationale (model-written) could echo a
            # field value, so it stays in the response and audit trail.
            escalated = self._escalate(
                change,
                f"{classification.category}; see /changes/{cid}/audit",
            )

        return ChangePropagationResponse(
            change_id=cid,
            employee_id=change.employee_id,
            status="conflict",
            conflicts=[c.render() for c in conflicts],
            classification=classification,
            escalated=escalated,
            message="No downstream systems were updated because validation failed.",
        )

    def _classify(
        self, change: EmployeeChangeRequest, conflicts: list[Conflict]
    ) -> ConflictClassification:
        try:
            raw = self.classifier.classify(change, conflicts)
        except Exception:  # classifier must never break propagation
            logger.exception("Classifier raised; using rules")
            raw = RuleBasedClassifier().classify(change, conflicts)
        return apply_guardrails(raw, change, conflicts)

    def _failed_with_rollback(
        self,
        change: EmployeeChangeRequest,
        failed_system: str,
        applied: list[str],
        error: ConnectorError,
    ) -> ChangePropagationResponse:
        cid = change.change_id
        field = change.field_name
        employee_id = change.employee_id

        stuck: list[str] = []
        for name in reversed(applied):
            connector = self.systems[name]
            try:
                self._retry(
                    lambda c=connector: c.write(
                        employee_id, field, change.old_value
                    )
                )
                self.store.audit(cid, "write_rolled_back", {"system": name})
            except ConnectorError as exc:
                stuck.append(name)
                self.store.audit(
                    cid,
                    "rollback_failed",
                    {"system": name, "error": str(exc)},
                )

        if stuck:
            reason = (
                f"write to {failed_system} failed and rollback failed for "
                f"{', '.join(stuck)}: systems are INCONSISTENT"
            )
            message = (
                f"Write to {failed_system} failed and could not restore "
                f"{', '.join(stuck)}. Manual reconciliation required."
            )
        else:
            reason = f"write to {failed_system} failed; changes rolled back ({error})"
            message = (
                f"Write to {failed_system} failed after retries; "
                "previously updated systems were restored."
            )

        escalated = self._escalate(change, reason)
        return ChangePropagationResponse(
            change_id=cid,
            employee_id=employee_id,
            status="failed",
            updated_systems=stuck,  # systems still holding the new value
            escalated=escalated,
            message=message,
        )

    def _escalate(self, change: EmployeeChangeRequest, reason: str) -> bool:
        # PII-safe: field and system names only, never the values themselves.
        text = (
            f":warning: Change {change.change_id} for {change.employee_id} "
            f"({change.field_name}) needs review: {reason}"
        )
        try:
            self.notifier.notify(ESCALATION_CHANNEL, text)
            self.store.audit(change.change_id, "escalated_to_slack")
            return True
        except Exception:
            logger.exception("Slack escalation failed")
            self.store.audit(change.change_id, "escalation_failed")
            return False
