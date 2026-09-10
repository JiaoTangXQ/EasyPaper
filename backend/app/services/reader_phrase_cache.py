"""Persist text correspondence, independent of an annotation's color or geometry."""

import hashlib
import json
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..models.reading import ReaderPhraseAlignment


class ReaderPhraseCache:
    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def key(document_id, context, candidates):
        # Include target glyphs so an edited PDF cannot inherit old coordinates.
        value = ["phrase-grounding-v1", document_id, [p["sentence"] for p in context], candidates]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    def get(self, key):
        with Session(self.engine) as session:
            row = session.get(ReaderPhraseAlignment, key)
            return json.loads(row.result_json) if row and row.result_json else None

    def put(self, key, document_id, result, started_at):
        value = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        with Session(self.engine) as session:
            row = session.get(ReaderPhraseAlignment, key)
            if row:
                session.execute(
                    update(ReaderPhraseAlignment)
                    .where(ReaderPhraseAlignment.id == key, ReaderPhraseAlignment.updated_at <= started_at)
                    .values(result_json=value, updated_at=datetime.utcnow())
                )
            else:
                session.add(ReaderPhraseAlignment(id=key, document_id=document_id, result_json=value))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()  # Another worker completed the same table.
            expired = session.exec(
                select(ReaderPhraseAlignment)
                .where(ReaderPhraseAlignment.document_id == document_id)
                .order_by(ReaderPhraseAlignment.updated_at.desc())
                .offset(256)
            ).all()
            for entry in expired:
                session.delete(entry)
            if expired:
                session.commit()

    def invalidate(self, document_id):
        # Tombstones stop an older in-flight request from undoing an explicit retry.
        with Session(self.engine) as session:
            session.execute(
                update(ReaderPhraseAlignment)
                .where(ReaderPhraseAlignment.document_id == document_id)
                .values(result_json="", updated_at=datetime.utcnow())
            )
            session.commit()
