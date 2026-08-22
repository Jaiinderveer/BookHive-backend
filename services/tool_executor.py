from datetime import timedelta
import re
from bson import ObjectId
from fastapi import HTTPException
from database.mongodb import DBHelper
from models.book import BookCreate, BookUpdate
from models.member import MemberCreate, MemberUpdate
from models.transaction import TransactionIssue, TransactionReturn
from services import book_service, member_service, transaction_service, dashboard_service
from services.activity_service import log_activity
from utils.dates import as_utc, days_overdue, utc_now

# Cap on how many candidates an ambiguity message spells out.
_MAX_LISTED_CANDIDATES = 5


def _normalized(value):
    """Trimmed text with internal runs of whitespace collapsed to one space."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip())


def _describe_candidates(descriptions):
    """Join candidate descriptions, spelling out only the first few."""
    listed = descriptions[:_MAX_LISTED_CANDIDATES]
    remaining = len(descriptions) - len(listed)
    if remaining > 0:
        listed = listed + [f"and {remaining} more"]
    return "; ".join(listed)


def _describe_members(members):
    """Librarian-facing details for members that a name could refer to.

    Membership ID and email are the identifiers a librarian works with. Internal
    MongoDB IDs are never included.
    """
    descriptions = []
    for member in members:
        detail = member.get("name") or "Unnamed member"
        identifiers = [
            part
            for part in (
                f"membership ID {member.get('membership_id')}" if member.get("membership_id") else "",
                member.get("email") or "",
            )
            if part
        ]
        if identifiers:
            detail += f" ({', '.join(identifiers)})"
        descriptions.append(detail)
    return _describe_candidates(descriptions)


def _describe_books(books):
    """Librarian-facing details for books that share a title. No internal IDs."""
    descriptions = []
    for book in books:
        detail = book.get("title") or "Untitled"
        if book.get("author"):
            detail += f" by {book['author']}"
        if book.get("isbn"):
            detail += f" (ISBN {book['isbn']})"
        descriptions.append(detail)
    return _describe_candidates(descriptions)


def _find_book_by_title(title, db, isbn=None):
    """Resolve exactly one book, or refuse rather than guessing.

    An ISBN, being unique, decides outright when the librarian supplies one.
    Otherwise the title must match exactly, ignoring capitalization and stray
    whitespace. When several books share that title the caller gets a 409
    listing the candidates instead of an arbitrary pick.
    """
    normalized_isbn = _normalized(isbn)
    if normalized_isbn:
        book = db.books.find_one({"isbn": normalized_isbn})
        if not book:
            raise HTTPException(
                status_code=404, detail=f"No book found with ISBN '{normalized_isbn}'"
            )
        return db.serialize(book)

    normalized_title = _normalized(title)
    if not normalized_title:
        return None

    pattern = f"^{re.escape(normalized_title)}$"
    matches = list(db.books.find({"title": {"$regex": pattern, "$options": "i"}}))
    if not matches:
        return None
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(matches)} books share the title '{normalized_title}': "
                f"{_describe_books(matches)}. "
                "Ask the librarian which ISBN to use, then retry with that isbn."
            ),
        )
    return db.serialize(matches[0])


def _find_member_by_name(name, db, membership_id=None):
    """Resolve exactly one member, or refuse rather than guessing.

    Resolution order:
      1. Membership ID, being unique, when the librarian supplies one.
      2. Exact name match, ignoring capitalization and stray whitespace.
      3. Partial name match, but only when it identifies a single member.

    Several matches never collapse to an arbitrary pick: the caller gets a 409
    listing the candidates so the librarian can choose. Returns None when
    nothing matches, leaving the caller's own "not found" message intact.
    """
    members = member_service.get_all_members(db)

    normalized_membership_id = _normalized(membership_id)
    if normalized_membership_id:
        target_id = normalized_membership_id.lower()
        for member in members:
            if _normalized(member.get("membership_id")).lower() == target_id:
                return member
        raise HTTPException(
            status_code=404,
            detail=f"No member found with membership ID '{normalized_membership_id}'",
        )

    normalized_name = _normalized(name)
    if not normalized_name:
        return None
    target_name = normalized_name.lower()

    exact = [m for m in members if _normalized(m.get("name")).lower() == target_name]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{len(exact)} members are named '{normalized_name}': "
                f"{_describe_members(exact)}. "
                "Ask the librarian which one, then retry with that membership_id."
            ),
        )

    partial = [m for m in members if target_name in _normalized(m.get("name")).lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{normalized_name}' matches {len(partial)} members: "
                f"{_describe_members(partial)}. "
                "Ask the librarian for the full name or membership ID, then retry."
            ),
        )

    return None


def _positive_int(args, key, default):
    """Read a whole-number argument the model supplied, or reject it clearly."""
    raw = args.get(key, default)
    if raw is None:
        raw = default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{key} must be a whole number")
    if value <= 0:
        raise HTTPException(status_code=400, detail=f"{key} must be greater than 0")
    return value


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
    missing = [field for field in required if args.get(field) is None or (isinstance(args.get(field), str) and not args.get(field).strip())]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required fields: {', '.join(missing)}")

    # Prevent the model from inventing placeholder metadata. These are not valid
    # librarian-supplied values for a new book.
    placeholders = {"unknown", "n/a", "na", "none", "null", "general", "not provided", "not specified"}
    invalid_placeholders = [
        field for field in ["author", "isbn", "category"]
        if isinstance(args.get(field), str) and args[field].strip().lower() in placeholders
    ]
    if invalid_placeholders:
        raise HTTPException(
            status_code=400,
            detail=f"Please provide real values for: {', '.join(invalid_placeholders)}. Do not use placeholders such as Unknown or General."
        )

    try:
        quantity = int(args.get("quantity"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Quantity must be a valid integer")

    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than 0")
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
    normalized_name = _normalized(args.get("name"))
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Missing required field: name")
    # A search legitimately returns every match, so the caller can see the
    # candidates. Matching ignores capitalization and stray whitespace.
    target = normalized_name.lower()
    members = member_service.get_all_members(db)
    return [member for member in members if target in _normalized(member.get("name")).lower()]

def _issue_book(args, db):
    book_title = args.get("book_title")
    member_name = args.get("member_name")
    isbn = args.get("isbn")
    membership_id = args.get("membership_id")

    if not (_normalized(book_title) or _normalized(isbn)):
        raise HTTPException(status_code=400, detail="Missing required field: book_title")
    if not (_normalized(member_name) or _normalized(membership_id)):
        raise HTTPException(status_code=400, detail="Missing required field: member_name")

    # Parsed before anything is resolved so a bad value cannot reach the mutation.
    due_days = _positive_int(args, "due_days", 14)

    book = _find_book_by_title(book_title, db, isbn=isbn)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{book_title}' not found")

    member = _find_member_by_name(member_name, db, membership_id=membership_id)
    if not member:
        raise HTTPException(status_code=404, detail=f"Member '{member_name}' not found")

    due_date = utc_now() + timedelta(days=due_days)
    trans_in = TransactionIssue(
        book_id=book["id"],
        member_id=member["id"],
        due_date=due_date,
    )
    transaction = transaction_service.issue_book(trans_in, db)
    return {
        "bookTitle": book.get("title", "Unknown Book"),
        "memberName": member.get("name", "Unknown Member"),
        "status": transaction.get("status", "Issued"),
        "issueDate": transaction.get("issue_date"),
        "dueDate": transaction.get("due_date"),
        "returnDate": transaction.get("return_date"),
        "fine": transaction.get("fine", 0),
        "overdue": False,
        "message": f"{book.get('title', 'Book')} was issued to {member.get('name', 'member')}."
    }

def _return_book(args, db):
    book_title = args.get("book_title")
    member_name = args.get("member_name")
    isbn = args.get("isbn")
    membership_id = args.get("membership_id")

    if not (_normalized(book_title) or _normalized(isbn)):
        raise HTTPException(status_code=400, detail="Missing required field: book_title")
    if not (_normalized(member_name) or _normalized(membership_id)):
        raise HTTPException(status_code=400, detail="Missing required field: member_name")

    book = _find_book_by_title(book_title, db, isbn=isbn)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{book_title}' not found")

    member = _find_member_by_name(member_name, db, membership_id=membership_id)
    if not member:
        raise HTTPException(status_code=404, detail=f"Member '{member_name}' not found")

    transaction = _find_issued_transaction(book["id"], member["id"], db)
    if not transaction:
        raise HTTPException(status_code=404, detail=f"No issued transaction found for '{book_title}' by '{member_name}'")

    trans_in = TransactionReturn(transaction_id=transaction["id"])
    returned = transaction_service.return_book(trans_in, db)
    return {
        "bookTitle": book.get("title", "Unknown Book"),
        "memberName": member.get("name", "Unknown Member"),
        "status": returned.get("status", "Returned"),
        "issueDate": returned.get("issue_date"),
        "dueDate": returned.get("due_date"),
        "returnDate": returned.get("return_date"),
        "fine": returned.get("fine", 0),
        "overdue": False,
        "message": f"{book.get('title', 'Book')} was returned by {member.get('name', 'member')}."
    }

def _dashboard_summary(args, db):
    return dashboard_service.get_dashboard_metrics(db)

def _list_transactions(args, db):
    """Return librarian-friendly transaction records without internal database IDs."""
    transactions = transaction_service.get_all_transactions(db)
    status = args.get("status")
    if status:
        transactions = [t for t in transactions if t.get("status", "").lower() == status.lower()]

    output = []
    for transaction in transactions:
        book = db.books.find_one({"_id": ObjectId(transaction["book_id"])}) if ObjectId.is_valid(transaction.get("book_id", "")) else None
        member = db.members.find_one({"_id": ObjectId(transaction["member_id"])}) if ObjectId.is_valid(transaction.get("member_id", "")) else None
        due_date = transaction.get("due_date")
        # Same Asia/Kolkata calendar rule as the fine calculation, so the flag
        # here can never disagree with the fine shown beside it.
        overdue = (
            transaction.get("status") == "Issued"
            and days_overdue(due_date) > 0
        )
        output.append({
            "bookTitle": book.get("title", "Unknown Book") if book else "Unknown Book",
            "memberName": member.get("name", "Unknown Member") if member else "Unknown Member",
            "status": transaction.get("status", "Unknown"),
            "issueDate": transaction.get("issue_date"),
            "dueDate": due_date,
            "returnDate": transaction.get("return_date"),
            "fine": transaction.get("fine", 0),
            "overdue": overdue,
        })
    return output

def _adjust_book_quantity(args, db):
    book_title = args.get("book_title")
    isbn = args.get("isbn")

    if not (_normalized(book_title) or _normalized(isbn)):
        raise HTTPException(status_code=400, detail="Missing required field: book_title")

    # Validated before the book is resolved so a bad delta cannot reach the write.
    try:
        quantity_delta = int(args.get("quantity_delta", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="quantity_delta must be a whole number")
    if quantity_delta == 0:
        raise HTTPException(status_code=400, detail="quantity_delta cannot be zero")

    book = _find_book_by_title(book_title, db, isbn=isbn)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{book_title}' not found")

    current_quantity = book.get("quantity")
    if not isinstance(current_quantity, int):
        raise HTTPException(
            status_code=409,
            detail=f"'{book.get('title', 'This book')}' has no valid quantity recorded",
        )

    new_quantity = current_quantity + quantity_delta
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
    isbn = args.get("isbn")
    membership_id = args.get("membership_id")

    if not (_normalized(book_title) or _normalized(isbn)):
        raise HTTPException(status_code=400, detail="Missing required field: book_title")
    if not (_normalized(member_name) or _normalized(membership_id)):
        raise HTTPException(status_code=400, detail="Missing required field: member_name")

    # Validated before anything is resolved so a bad value cannot reach the write.
    days = _positive_int(args, "days", 7)

    book = _find_book_by_title(book_title, db, isbn=isbn)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book '{book_title}' not found")

    member = _find_member_by_name(member_name, db, membership_id=membership_id)
    if not member:
        raise HTTPException(status_code=404, detail=f"Member '{member_name}' not found")

    transaction = _find_issued_transaction(book["id"], member["id"], db)
    if not transaction:
        raise HTTPException(status_code=404, detail=f"No issued transaction found for '{book_title}' by '{member_name}'")

    current_due_date = as_utc(transaction.get("due_date"))
    if current_due_date is None:
        raise HTTPException(
            status_code=409, detail="This transaction has no valid due date to extend"
        )

    new_due_date = current_due_date + timedelta(days=days)
    db.transactions.update_one(
        {"_id": ObjectId(transaction["id"])},
        {"$set": {"due_date": new_due_date}},
    )
    updated_trans = db.transactions.find_one({"_id": ObjectId(transaction["id"])})
    log_activity(
        db,
        "Due Date Extended",
        f"Due date for '{book.get('title', 'a book')}' extended by {days} days "
        f"for {member.get('name', 'a member')}",
    )
    return db.serialize(updated_trans)