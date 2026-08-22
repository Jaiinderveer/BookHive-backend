from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=30)
    address: Optional[str] = None
    role: str = "member"

class UserOut(BaseModel):
    id: str
    username: str
    email: EmailStr
    role: str
class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, min_length=1, max_length=30)
    address: Optional[str] = None

    @field_validator("name", "phone")
    @classmethod
    def reject_blank_required_field(cls, value):
        """A profile must keep a name and a phone, so neither can be blanked."""
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("This field is required and cannot be empty")
        return trimmed

    @field_validator("address")
    @classmethod
    def normalize_optional_field(cls, value):
        """Address is optional, so a blank value clears it instead of storing spaces."""
        if value is None:
            return None
        return value.strip() or None

class Token(BaseModel):
    access_token: str
    token_type: str
class ProfileOut(BaseModel):
    id: str
    username: str
    name: str
    email: EmailStr
    phone: str
    address: Optional[str] = None
    role: str
class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None
class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)