"""Authenticated user preference APIs."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from ..core.db import engine
from ..models.knowledge import UserSetting
from ..models.user import User
from ..services.user_preferences import get_preferences, save_preferences
from .deps import get_current_user


class GlossPreferences(BaseModel):
    model_config = ConfigDict(extra="allow")

    auto_speak: bool = False
    preparation: Literal["server", "remote_worker"] = "server"


class ReadingPreferences(BaseModel):
    model_config = ConfigDict(extra="allow")

    gloss: GlossPreferences = Field(default_factory=GlossPreferences)


class UserPreferences(BaseModel):
    model_config = ConfigDict(extra="allow")

    reading: ReadingPreferences = Field(default_factory=ReadingPreferences)


class UserPreferencesResponse(UserPreferences):
    updated_at: str | None = None


router = APIRouter(prefix="/api/settings", tags=["settings"])


def _response(value: dict[str, Any], updated_at: str | None = None) -> UserPreferencesResponse:
    return UserPreferencesResponse.model_validate({**value, "updated_at": updated_at})


@router.get("/preferences", response_model=UserPreferencesResponse)
def read_preferences(user: User = Depends(get_current_user)) -> UserPreferencesResponse:
    with Session(engine) as session:
        value = get_preferences(session, user.id)
        setting = session.get(UserSetting, f"user:{user.id}:preferences")
        updated_at = setting.updated_at.isoformat() if setting and setting.updated_at else None
    return _response(value, updated_at)


@router.put("/preferences", response_model=UserPreferencesResponse)
def write_preferences(
    payload: UserPreferences,
    user: User = Depends(get_current_user),
) -> UserPreferencesResponse:
    with Session(engine) as session:
        value = save_preferences(session, user.id, payload.model_dump())
        setting = session.get(UserSetting, f"user:{user.id}:preferences")
        updated_at = setting.updated_at.isoformat() if setting and setting.updated_at else None
    return _response(value, updated_at)
