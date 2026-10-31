from datetime import datetime

from pydantic import field_validator
from sqlmodel import Field, SQLModel


class UserBase(SQLModel):
    email: str = Field(unique=True, index=True)
    is_active: bool = Field(default=True)


class User(UserBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    token_version: int = Field(default=0)
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserCreate(UserBase):
    password: str

    @field_validator("password")
    @classmethod
    def password_policy(cls, value: str) -> str:
        return validate_password(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        from email_validator import validate_email

        return validate_email(value.strip(), check_deliverability=False).normalized.lower()


class UserRead(UserBase):
    id: int
    created_at: datetime


class Token(SQLModel, table=False):
    access_token: str
    token_type: str


class TokenPayload(SQLModel):
    sub: int | None = None


def validate_password(value: str) -> str:
    if len(value) < 12 or len(value.encode("utf-8")) > 72:
        raise ValueError("密码至少 12 个字符，UTF-8 编码后不能超过 72 字节")
    return value
