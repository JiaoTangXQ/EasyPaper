"""Personal terminology memory and lightweight spaced review."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..core.db import engine
from ..models.knowledge import PaperKnowledge, PersonalTerm
from ..models.task import Task
from ..models.user import User
from ..services.paper_passport import normalize_term
from .deps import get_current_user


class TermUpsert(BaseModel):
    term: str = Field(min_length=1, max_length=300)
    meaning: str = Field(default="", max_length=1000)
    definition: str = Field(default="", max_length=3000)
    paper_id: str | None = None
    task_id: str | None = None
    block_id: str | None = None
    source_quote: str = Field(default="", max_length=5000)
    notes: str = Field(default="", max_length=5000)


class TermReview(BaseModel):
    quality: int = Field(ge=0, le=5)


def _utc(value: datetime | None) -> str | None:
    """Stored datetimes are naive UTC; say so, or browsers read them as local time."""
    if value is None:
        return None
    return value.isoformat() + ("Z" if value.tzinfo is None else "")


def _term_dict(term: PersonalTerm) -> dict:
    return {
        "id": term.id,
        "term": term.term,
        "meaning": term.meaning,
        "definition": term.definition,
        "paper_id": term.paper_id,
        "task_id": term.task_id,
        "block_id": term.block_id,
        "source_quote": term.source_quote,
        "notes": term.notes,
        "times_seen": term.times_seen,
        "repetitions": term.repetitions,
        "next_review": _utc(term.next_review),
        "last_review": _utc(term.last_review),
    }


def create_term_router() -> APIRouter:
    router = APIRouter(prefix="/api/terms", tags=["terms"])

    @router.get("")
    async def list_terms(
        due_only: bool = False,
        q: str = "",
        limit: int = 100,
        user: User = Depends(get_current_user),
    ) -> list[dict]:
        limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(PersonalTerm).where(PersonalTerm.user_id == user.id)
            if due_only:
                statement = statement.where(PersonalTerm.next_review <= datetime.utcnow())
            if q.strip():
                statement = statement.where(PersonalTerm.normalized_term.contains(normalize_term(q), autoescape=True))
            terms = session.exec(statement.order_by(PersonalTerm.next_review.asc()).limit(limit)).all()
        return [_term_dict(term) for term in terms]

    @router.post("")
    async def upsert_term(payload: TermUpsert, user: User = Depends(get_current_user)) -> dict:
        normalized = normalize_term(payload.term)
        if not normalized:
            raise HTTPException(422, "术语不能为空")
        with Session(engine) as session:
            if payload.paper_id:
                paper = session.get(PaperKnowledge, payload.paper_id)
                if not paper or paper.user_id != user.id:
                    raise HTTPException(404, "论文不存在或无权访问")
            if payload.task_id:
                task = session.get(Task, payload.task_id)
                if not task or task.user_id != user.id:
                    raise HTTPException(404, "论文任务不存在或无权访问")
            term = session.exec(
                select(PersonalTerm).where(
                    PersonalTerm.user_id == user.id,
                    PersonalTerm.normalized_term == normalized,
                )
            ).first()
            if term:
                term.term = payload.term.strip()
                term.meaning = payload.meaning or term.meaning
                term.definition = payload.definition or term.definition
                term.paper_id = payload.paper_id or term.paper_id
                term.task_id = payload.task_id or term.task_id
                term.block_id = payload.block_id or term.block_id
                term.source_quote = payload.source_quote or term.source_quote
                term.notes = payload.notes or term.notes
                term.times_seen += 1
                term.updated_at = datetime.utcnow()
            else:
                term = PersonalTerm(
                    id=f"term_{uuid.uuid4().hex[:16]}",
                    user_id=user.id,
                    normalized_term=normalized,
                    term=payload.term.strip(),
                    meaning=payload.meaning,
                    definition=payload.definition,
                    paper_id=payload.paper_id,
                    task_id=payload.task_id,
                    block_id=payload.block_id,
                    source_quote=payload.source_quote,
                    notes=payload.notes,
                )
            session.add(term)
            session.commit()
            session.refresh(term)
            return _term_dict(term)

    @router.post("/{term_id}/review")
    async def review_term(term_id: str, payload: TermReview, user: User = Depends(get_current_user)) -> dict:
        with Session(engine) as session:
            term = session.get(PersonalTerm, term_id)
            if not term or term.user_id != user.id:
                raise HTTPException(404, "术语不存在")
            quality = payload.quality
            if quality < 3:
                term.repetitions = 0
                term.interval_days = 1.0
            else:
                term.repetitions += 1
                term.interval_days = (
                    1.0
                    if term.repetitions == 1
                    else 6.0
                    if term.repetitions == 2
                    else max(1.0, term.interval_days * term.ease_factor)
                )
                term.ease_factor = max(1.3, term.ease_factor + 0.1 - (5 - quality) * 0.08)
            term.last_review = datetime.utcnow()
            term.next_review = term.last_review + timedelta(days=term.interval_days)
            term.updated_at = term.last_review
            session.add(term)
            session.commit()
            session.refresh(term)
            return _term_dict(term)

    @router.delete("/{term_id}")
    async def delete_term(term_id: str, user: User = Depends(get_current_user)) -> dict[str, str]:
        with Session(engine) as session:
            term = session.get(PersonalTerm, term_id)
            if not term or term.user_id != user.id:
                raise HTTPException(404, "术语不存在")
            session.delete(term)
            session.commit()
        return {"status": "deleted"}

    return router
