"""Stable source identity shared by imports, reading and knowledge features."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from sqlmodel import Session

from ..models.knowledge import PaperPassport


def fingerprint_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def get_or_create_passport(engine, user_id: int, data: bytes, title: str = "") -> PaperPassport:
    fingerprint = fingerprint_bytes(data)
    passport_id = f"pp_{user_id}_{fingerprint[:32]}"
    with Session(engine) as session:
        passport = session.get(PaperPassport, passport_id)
        if passport:
            if title and not passport.title:
                passport.title = title
                passport.updated_at = datetime.utcnow()
                session.add(passport)
                session.commit()
                session.refresh(passport)
            return passport
        passport = PaperPassport(
            id=passport_id,
            user_id=user_id,
            fingerprint=fingerprint,
            title=title or "",
        )
        session.add(passport)
        try:
            session.commit()
        except Exception:
            session.rollback()
            passport = session.get(PaperPassport, passport_id)
            if passport:
                return passport
            raise
        session.refresh(passport)
        return passport
