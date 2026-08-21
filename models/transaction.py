from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime, timezone

class TransactionIssue(BaseModel):
    book_id: str
    member_id: str
    due_date: datetime

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, value):
        if value <= datetime.now(timezone.utc):
            raise ValueError("Due date must be in the future")
        return value
class TransactionReturn(BaseModel):
    transaction_id: str

class TransactionOut(BaseModel):
    id: str
    book_id: str
    member_id: str
    issue_date: datetime
    due_date: datetime
    return_date: Optional[datetime] = None
    fine: float = 0.0
    status: str