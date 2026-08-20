from pydantic import BaseModel, Field, model_validator
from typing import Optional
from datetime import datetime

class BookBase(BaseModel):
    title: str
    author: str
    isbn: str
    category: str
    publisher: Optional[str] = None
    publication_year: Optional[int] = None
    quantity: int = Field(ge=0)
    available_quantity: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_available_quantity(self):
        if self.available_quantity > self.quantity:
            raise ValueError("available_quantity cannot exceed quantity")
        return self

class BookCreate(BookBase):
    pass

class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    isbn: Optional[str] = None
    category: Optional[str] = None
    publisher: Optional[str] = None
    publication_year: Optional[int] = None
    quantity: Optional[int] = Field(default=None, ge=0)
    available_quantity: Optional[int] = Field(default=None, ge=0)

class BookOut(BookBase):
    id: str
    created_at: datetime
