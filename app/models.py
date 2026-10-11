# app/models.py

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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


class ChangePropagationResponse(BaseModel):
    """Result of validating and propagating an employee change."""

    change_id: str
    employee_id: str
    status: Literal["propagated", "conflict", "failed"]
    updated_systems: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    message: str
