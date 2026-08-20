from pydantic import BaseModel, EmailStr, Field
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
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None

class MemberAccountCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)

class MemberOut(MemberBase):
    id: str
    created_at: datetime
    user_id: Optional[str] = None
    membership_id: str
