from fastapi import HTTPException
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from datetime import datetime
from database.mongodb import DBHelper
from models.book import BookCreate, BookUpdate
from services.activity_service import log_activity
import re


def _escape_regex(text: str) -> str:
    """Escape special regex characters for exact matching."""
    return re.escape(text)


def find_book_by_title_exact(title: str, db: DBHelper):
    """
    Find a book by exact title match (case-insensitive).
    Uses ^<escaped title>$ with $options: "i" for exact case-insensitive matching.
    """
    if not title or not title.strip():
        return None
    escaped_title = _escape_regex(title.strip())
    query = {"title": {"$regex": f"^{escaped_title}$", "$options": "i"}}
    book = db.books.find_one(query)
    return db.serialize(book) if book else None


def create_book(book_in: BookCreate, db: DBHelper):
    book_dict = book_in.model_dump()
    book_dict["created_at"] = datetime.utcnow()
    
    try:
        result = db.books.insert_one(book_dict)
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="A book with this ISBN already exists")
    created_book = db.books.find_one({"_id": result.inserted_id})
    log_activity(db, "Book Added", f"{created_book['title']} added ({created_book['quantity']} copies)")
    return db.serialize(created_book)


def get_books(title: str, author: str, isbn: str, category: str, db: DBHelper):
    query = {}
    if title:
        query["title"] = {"$regex": title, "$options": "i"}
    if author:
        query["author"] = {"$regex": author, "$options": "i"}
    if isbn:
        query["isbn"] = isbn
    if category:
        query["category"] = {"$regex": category, "$options": "i"}

    books = db.books.find(query)
    return db.serialize_list(books)


def get_book_by_id(id: str, db: DBHelper):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Book ID")
    book = db.books.find_one({"_id": ObjectId(id)})
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return db.serialize(book)


def update_book(id: str, book_in: BookUpdate, db: DBHelper):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Book ID")
    
    update_data = {k: v for k, v in book_in.model_dump().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No data provided to update")
    
    book = db.books.find_one({"_id": ObjectId(id)})
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    issued_count = db.transactions.count_documents({"book_id": id, "status": "Issued"})
    quantity = update_data.get("quantity", book["quantity"])
    requested_available = update_data.get("available_quantity")
    if quantity < issued_count:
        raise HTTPException(status_code=400, detail="Quantity cannot be lower than the number of issued copies")
    if requested_available is not None and requested_available != quantity - issued_count:
        raise HTTPException(status_code=400, detail="Available quantity must equal quantity minus issued copies")
    
    # Availability is derived from stock and active loans, preventing manual drift.
    if "quantity" in update_data or requested_available is not None:
        update_data["quantity"] = quantity
        update_data["available_quantity"] = quantity - issued_count
    
    try:
        db.books.update_one({"_id": ObjectId(id)}, {"$set": update_data})
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="A book with this ISBN already exists")
        
    updated_book = db.books.find_one({"_id": ObjectId(id)})
    log_activity(db, "Book Updated", f"Details for {updated_book['title']} updated")
    return db.serialize(updated_book)


def delete_book(id: str, db: DBHelper):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Book ID")
    if db.transactions.count_documents({"book_id": id}) > 0:
        raise HTTPException(status_code=409, detail="Cannot delete a book with transaction history")
    result = db.books.delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Book not found")
    return {"detail": "Book deleted successfully"}