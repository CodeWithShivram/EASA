import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.passwords import MAX_PASSWORD_CHARS
from app.core.roles import Role


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    role: Role
    is_active: bool
    # Temporarily locked after repeated failed sign-ins.
    locked: bool
    created_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)
    role: Role


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> UpdateUserRequest:
        if self.role is None and self.is_active is None:
            raise ValueError("give role and/or is_active")
        return self


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)
