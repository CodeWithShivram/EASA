import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.passwords import MAX_PASSWORD_CHARS
from app.core.roles import Role


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    # Not checked against the policy here: a wrong password simply fails.
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)


class CurrentUser(BaseModel):
    user_id: uuid.UUID
    username: str
    role: Role
    tenant_id: uuid.UUID
    permissions: list[str]


class LoginResponse(BaseModel):
    token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - a scheme name, not a secret
    expires_at: datetime
    user: CurrentUser
