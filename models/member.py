from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime

class MemberBase(BaseModel):
    name: str
    email: EmailStr
    phone: str
    address: Optional[str] = None

class MemberCreate(MemberBase):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)

class MemberUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=30)
    address: Optional[str] = None

    @field_validator("name", "phone")
    @classmethod
    def reject_blank_required_field(cls, value):
        """A member must keep a name and a phone, so neither can be blanked."""
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("This field is required and cannot be empty")
        return trimmed

class MemberAccountCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)

class MemberOut(MemberBase):
    id: str
    created_at: datetime
    user_id: Optional[str] = None
    membership_id: str
