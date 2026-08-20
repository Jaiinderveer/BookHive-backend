from fastapi import APIRouter, Depends
from typing import List, Optional
from database.mongodb import get_db, DBHelper
from models.book import BookCreate, BookUpdate, BookOut
from utils.jwt import get_current_user, get_current_librarian
from services import book_service

router = APIRouter(prefix="/books", tags=["Books"])

@router.post("/", response_model=BookOut)
def create_book(book_in: BookCreate, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return book_service.create_book(book_in, db)

@router.get("/", response_model=List[BookOut])
def get_books(
    title: Optional[str] = None, 
    author: Optional[str] = None,
    isbn: Optional[str] = None,
    category: Optional[str] = None,
    db: DBHelper = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    return book_service.get_books(title, author, isbn, category, db)

@router.get("/{id}", response_model=BookOut)
def get_book(id: str, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_user)):
    return book_service.get_book_by_id(id, db)

@router.put("/{id}", response_model=BookOut)
def update_book(id: str, book_in: BookUpdate, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return book_service.update_book(id, book_in, db)

@router.delete("/{id}")
def delete_book(id: str, db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return book_service.delete_book(id, db)
