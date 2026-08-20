from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class TransactionIssue(BaseModel):
    book_id: str
    member_id: str
    due_date: datetime

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