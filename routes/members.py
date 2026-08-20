from fastapi import APIRouter, Depends
from typing import List
from database.mongodb import get_db, DBHelper
from models.member import MemberCreate, MemberUpdate, MemberOut, MemberAccountCreate
from utils.jwt import get_current_librarian
from services import member_service

router = APIRouter(prefix="/members", tags=["Members"])

@router.post("/", response_model=MemberOut)
def create_member(member_in: MemberCreate, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return member_service.create_member(member_in, db)

@router.get("/", response_model=List[MemberOut])
def get_members(db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return member_service.get_all_members(db)

@router.get("/{id}", response_model=MemberOut)
def get_member(id: str, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return member_service.get_member_by_id(id, db)

@router.post("/{id}/account", response_model=MemberOut)
def create_member_account(id: str, account_in: MemberAccountCreate, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return member_service.create_member_account(id, account_in, db)

@router.put("/{id}", response_model=MemberOut)
def update_member(id: str, member_in: MemberUpdate, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return member_service.update_member(id, member_in, db)

@router.delete("/{id}")
def delete_member(id: str, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return member_service.delete_member(id, db)
