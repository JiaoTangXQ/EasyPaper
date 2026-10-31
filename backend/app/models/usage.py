from sqlmodel import Field, SQLModel


class DailyUsage(SQLModel, table=True):
    """Persistent admission counts, keyed by UTC day and user; not token billing."""

    id: str = Field(primary_key=True)
    count: int = 0
