"""User-scoped product preferences shared by the reader and settings page."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlmodel import Session

from ..models.knowledge import UserSetting

PREFERENCES_SETTING_KEY = "preferences"
DEFAULT_PREFERENCES: dict[str, Any] = {
    "reading": {
        "gloss": {
            "auto_speak": False,
        },
    },
}


def _setting_id(user_id: int) -> str:
    return f"user:{user_id}:{PREFERENCES_SETTING_KEY}"


def _merge_preferences(value: Any) -> dict[str, Any]:
    """Fill defaults without discarding sections added by newer clients."""
    result = deepcopy(value) if isinstance(value, dict) else {}
    reading = result.setdefault("reading", {})
    if not isinstance(reading, dict):
        reading = result["reading"] = {}
    gloss = reading.setdefault("gloss", {})
    if not isinstance(gloss, dict):
        gloss = reading["gloss"] = {}
    if not isinstance(gloss.get("auto_speak"), bool):
        gloss["auto_speak"] = DEFAULT_PREFERENCES["reading"]["gloss"]["auto_speak"]
    return result


def get_preferences(session: Session, user_id: int) -> dict[str, Any]:
    setting = session.get(UserSetting, _setting_id(user_id))
    if not setting:
        return deepcopy(DEFAULT_PREFERENCES)
    try:
        value = json.loads(setting.value_json)
    except (TypeError, json.JSONDecodeError):
        value = None
    return _merge_preferences(value)


def save_preferences(session: Session, user_id: int, value: dict[str, Any]) -> dict[str, Any]:
    normalized = _merge_preferences(value)
    setting = session.get(UserSetting, _setting_id(user_id))
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if not setting:
        setting = UserSetting(
            id=_setting_id(user_id),
            user_id=user_id,
            key=PREFERENCES_SETTING_KEY,
            value_json=encoded,
        )
    else:
        setting.value_json = encoded
        setting.updated_at = datetime.utcnow()
    session.add(setting)
    session.commit()
    return normalized
