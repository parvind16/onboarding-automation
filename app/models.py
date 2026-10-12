# app/models.py

from datetime import date
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)


class OnboardingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    employee_id: str = Field(min_length=2, max_length=50)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    department: str = Field(min_length=2, max_length=100)
    manager_email: EmailStr
    start_date: date
    equipment_required: bool = True
    work_location: str | None = Field(default=None, max_length=100)
    shipping_address: str | None = Field(default=None, max_length=300)


class OnboardingResponse(BaseModel):
    employee_id: str
    status: Literal["completed", "failed"]
    completed_steps: list[str] = Field(default_factory=list)
    failed_step: str | None = None
    message: str


class EmployeeChangeRequest(BaseModel):
    """A change event received from the source-of-truth system, Ashby."""

    model_config = ConfigDict(str_strip_whitespace=True)

    change_id: str = Field(min_length=3, max_length=100)
    employee_id: str = Field(min_length=2, max_length=50)
    source_system: Literal["ashby"] = "ashby"

    field_name: Literal[
        "department",
        "manager_email",
        "start_date",
        "work_location",
    ]

    old_value: str = Field(min_length=1, max_length=300)
    new_value: str = Field(min_length=1, max_length=300)
    requested_by: EmailStr

    @model_validator(mode="after")
    def check_value_formats(self) -> "EmployeeChangeRequest":
        """Catch malformed values at the edge, before any system is read."""
        if self.old_value == self.new_value:
            raise ValueError("old_value and new_value must differ.")

        if self.field_name == "start_date":
            for label, value in (
                ("old_value", self.old_value),
                ("new_value", self.new_value),
            ):
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(
                        f"{label} must be an ISO date (YYYY-MM-DD)."
                    ) from exc

        if self.field_name == "manager_email":
            for label, value in (
                ("old_value", self.old_value),
                ("new_value", self.new_value),
            ):
                try:
                    TypeAdapter(EmailStr).validate_python(value)
                except ValidationError as exc:
                    raise ValueError(
                        f"{label} must be a valid email address."
                    ) from exc

        return self


class Conflict(BaseModel):
    """One disagreement found while validating a change across systems."""

    system: str
    expected: str
    found: str | None

    def render(self) -> str:
        if self.system == "ashby":
            return (
                f"ashby: expected approved value '{self.expected}', "
                f"found '{self.found}'."
            )
        return (
            f"{self.system}: expected '{self.expected}', "
            f"found '{self.found}'."
        )


ConflictCategory = Literal[
    "source_not_updated",
    "stale_target",
    "missing_target_record",
    "concurrent_edit",
    "needs_human",
]

RecommendedAction = Literal[
    "retry_after_source_sync",
    "refresh_expected_old_value",
    "escalate_to_human",
    "reject_change",
]


class ConflictClassification(BaseModel):
    """Advisory triage of a conflict. Never triggers a write by itself."""

    category: ConflictCategory
    recommended_action: RecommendedAction
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(max_length=500)
    classified_by: Literal["claude", "rules"] = "rules"
    guardrail_applied: str | None = None


class ChangePropagationResponse(BaseModel):
    """Result of validating and propagating an employee change."""

    change_id: str
    employee_id: str
    status: Literal["propagated", "conflict", "failed"]
    updated_systems: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    classification: ConflictClassification | None = None
    escalated: bool = False
    message: str
