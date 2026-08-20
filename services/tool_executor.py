from datetime import datetime, timedelta
from bson import ObjectId
from fastapi import HTTPException
from database.mongodb import DBHelper
from models.book import BookCreate, BookUpdate
from models.member import MemberCreate, MemberUpdate
from models.transaction import TransactionIssue, TransactionReturn
from services import book_service, member_service, transaction_service, dashboard_service
from services.activity_service import log_activity

def _find_book_by_title(title, db):
    books = book_service.get_books(title, None, None, None, db)
    if not books:
        return None
    return books[0]

def _find_member_by_name(name, db):
    members = member_service.get_all_members(db)
    for member in members:
        if name.lower() in member.get("name", "").lower():
            return member
    return None

def _find_issued_transaction(book_id, member_id, db):
    transactions = transaction_service.get_all_transactions(db)
    for transaction in transactions:
        if (
            transaction.get("book_id") == book_id
            and transaction.get("member_id") == member_id
            and transaction.get("status", "").lower() == "issued"
        ):
            return transaction
    return None

def execute_tool(tool_name: str, arguments: dict, db: DBHelper):
    handlers = {
        "create_book": _create_book,
        "update_book": _update_book,
        "delete_book": _delete_book,
        "search_book": _search_book,
        "list_books": _list_books,
        "create_member": _create_member,
        "update_member": _update_member,
        "delete_member": _delete_member,
        "search_member": _search_member,
        "issue_book": _issue_book,
        "return_book": _return_book,
        "dashboard_summary": _dashboard_summary,
        "list_transactions": _list_transactions,
        "adjust_book_quantity": _adjust_book_quantity,
        "extend_due_date": _extend_due_date,
    }

    handler = handlers.get(tool_name)
    if not handler:
        raise HTTPException(status_code=400, detail=f"Invalid tool: {tool_name}")

    return handler(arguments, db)

def _create_book(args, db):
    required = ["title", "author", "isbn", "category", "quantity"]
    missing = [field for field in required if not args.get(field)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")

    quantity = int(args.get("quantity", 0))
    book_in = BookCreate(
        title=args["title"],
        author=args["author"],
        isbn=args["isbn"],
        category=args["category"],
        publisher=args.get("publisher"),
        publication_year=args.get("publication_year"),
        quantity=quantity,
        available_quantity=quantity,
    )
    return book_service.create_book(book_in, db)

def _update_book(args, db):
    book_id = args.get("book_id")
    if not book_id:
        raise HTTPException(status_code=400, detail="Missing required field: book_id")

    update_data = {}
    for field in ["title", "author", "isbn", "category", "publisher", "publication_year", "quantity", "available_quantity"]:
        if field in args and args[field] is not None:
            update_data[field] = args[field]

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    book_in = BookUpdate(**update_data)
    return book_service.update_book(book_id, book_in, db)

def _delete_book(args, db):
    book_id = args.get("book_id")
    if not book_id:
        raise HTTPException(status_code=400, detail="Missing required field: book_id")
    return book_service.delete_book(book_id, db)

def _search_book(args, db):
    title = args.get("title")
    author = args.get("author")
    isbn = args.get("isbn")
    category = args.get("category")
    return book_service.get_books(title, author, isbn, category, db)

def _list_books(args, db):
    return book_service.get_books(None, None, None, None, db)

def _create_member(args, db):
    required = ["name", "email", "phone", "username", "password"]
    missing = [field for field in required if not args.get(field)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")

    member_in = MemberCreate(
        name=args["name"],
        email=args["email"],
        phone=args["phone"],
        address=args.get("address"),
        username=args["username"],
        password=args["password"],
    )
    return member_service.create_member(member_in, db)

def _update_member(args, db):
    member_id = args.get("member_id")
    if not member_id:
        raise HTTPException(status_code=400, detail="Missing required field: member_id")

    update_data = {}
    for field in ["name", "email", "phone", "address"]:
        if field in args and args[field] is not None:
            update_data[field] = args[field]

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    member_in = MemberUpdate(**update_data)
    return member_service.update_member(member_id, member_in, db)

def _delete_member(args, db):
    member_id = args.get("member_id")
    if not member_id:
        raise HTTPException(status_code=400, detail="Missing required field: member_id")
    return member_service.delete_member(member_id, db)

def _search_member(args, db):
    name = args.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Missing required field: name")
    members = member_service.get_all_members(db)
    return [member for member in members if name.lower() in member.get("name", "").lower()]

def _issue_book(args, db):
    book_title = args.get("book_title")
    member_name = args.get("member_name")
    due_days = int(args.get("due_days", 14))

    if not book_title or not member_name:
        raise HTTPException(status_code=400, detail="Missing required fields: book_title, member_name")

    book = _find_book_by_title(book_title, db)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{book_title}' not found")

    member = _find_member_by_name(member_name, db)
    if not member:
        raise HTTPException(status_code=404, detail=f"Member '{member_name}' not found")

    due_date = datetime.utcnow() + timedelta(days=due_days)
    trans_in = TransactionIssue(
        book_id=book["id"],
        member_id=member["id"],
        due_date=due_date,
    )
    return transaction_service.issue_book(trans_in, db)

def _return_book(args, db):
    book_title = args.get("book_title")
    member_name = args.get("member_name")

    if not book_title or not member_name:
        raise HTTPException(status_code=400, detail="Missing required fields: book_title, member_name")

    book = _find_book_by_title(book_title, db)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{book_title}' not found")

    member = _find_member_by_name(member_name, db)
    if not member:
        raise HTTPException(status_code=404, detail=f"Member '{member_name}' not found")

    transaction = _find_issued_transaction(book["id"], member["id"], db)
    if not transaction:
        raise HTTPException(status_code=404, detail=f"No issued transaction found for '{book_title}' by '{member_name}'")

    trans_in = TransactionReturn(transaction_id=transaction["id"])
    return transaction_service.return_book(trans_in, db)

def _dashboard_summary(args, db):
    return dashboard_service.get_dashboard_metrics(db)

def _list_transactions(args, db):
    transactions = transaction_service.get_all_transactions(db)
    status = args.get("status")
    if status:
        transactions = [t for t in transactions if t.get("status", "").lower() == status.lower()]
    return transactions

def _adjust_book_quantity(args, db):
    book_title = args.get("book_title")
    quantity_delta = int(args.get("quantity_delta", 0))

    if not book_title:
        raise HTTPException(status_code=400, detail="Missing required field: book_title")
    if quantity_delta == 0:
        raise HTTPException(status_code=400, detail="quantity_delta cannot be zero")

    book = _find_book_by_title(book_title, db)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{book_title}' not found")

    new_quantity = book["quantity"] + quantity_delta
    if new_quantity < 0:
        new_quantity = 0

    issued_count = db.transactions.count_documents({"book_id": book["id"], "status": "Issued"})
    new_available = new_quantity - issued_count
    if new_available < 0:
        new_available = 0

    update_data = {
        "quantity": new_quantity,
        "available_quantity": new_available,
    }
    book_in = BookUpdate(**update_data)
    updated_book = book_service.update_book(book["id"], book_in, db)
    log_activity(db, "Book Quantity Adjusted", f"Adjusted '{updated_book['title']}' quantity by {quantity_delta} to {new_quantity} copies")
    return {
        "book": updated_book,
        "quantity_delta": quantity_delta,
        "message": f"Adjusted '{updated_book['title']}' quantity to {new_quantity} copies.",
    }

def _extend_due_date(args, db):
    book_title = args.get("book_title")
    member_name = args.get("member_name")
    days = int(args.get("days", 7))

    if not book_title or not member_name:
        raise HTTPException(status_code=400, detail="Missing required fields: book_title, member_name")

    book = _find_book_by_title(book_title, db)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{book_title}' not found")

    member = _find_member_by_name(member_name, db)
    if not member:
        raise HTTPException(status_code=404, detail=f"Member '{member_name}' not found")

    transaction = _find_issued_transaction(book["id"], member["id"], db)
    if not transaction:
        raise HTTPException(status_code=404, detail=f"No issued transaction found for '{book_title}' by '{member_name}'")

    new_due_date = transaction["due_date"] + timedelta(days=days)
    db.transactions.update_one(
        {"_id": ObjectId(transaction["_id"])},
        {"$set": {"due_date": new_due_date}},
    )
    updated_trans = db.transactions.find_one({"_id": ObjectId(transaction["_id"])})
    log_activity(db, "Due Date Extended", f"Due date for '{book['title']}' extended by {days} days for {member['name']}")
    return db.serialize(updated_trans)
