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


class OnboardingResponse(BaseModel):
    employee_id: str
    status: Literal["completed", "failed"]
    completed_steps: list[str] = Field(default_factory=list)
    failed_step: str | None = None
    message: str