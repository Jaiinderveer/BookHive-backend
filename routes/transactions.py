from fastapi import APIRouter, Depends, HTTPException
from typing import List
from database.mongodb import get_db, DBHelper
from models.transaction import TransactionIssue, TransactionReturn, TransactionOut
from utils.jwt import get_current_librarian, get_current_user
from services import transaction_service

router = APIRouter(prefix="/transactions", tags=["Transactions"])

@router.post("/issue", response_model=TransactionOut)
def issue_book(trans_in: TransactionIssue, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return transaction_service.issue_book(trans_in, db)

@router.post("/return", response_model=TransactionOut)
def return_book(trans_in: TransactionReturn, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return transaction_service.return_book(trans_in, db)

@router.get("/", response_model=List[TransactionOut])
def get_transactions(db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return transaction_service.get_all_transactions(db)

@router.get("/my", response_model=List[TransactionOut])
def get_my_transactions(db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_user)):
    member = db.members.find_one({"user_id": current_user["id"]})
    if not member:
        raise HTTPException(status_code=404, detail="Member profile not found")
    return transaction_service.get_transactions_by_member(str(member["_id"]), db)

@router.get("/{id}", response_model=TransactionOut)
def get_transaction(id: str, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return transaction_service.get_transaction_by_id(id, db)

@router.get("/book/{book_id}", response_model=List[TransactionOut])
def get_book_transactions(book_id: str, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return transaction_service.get_transactions_by_book(book_id, db)
