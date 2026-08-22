from fastapi import HTTPException
from bson import ObjectId
from database.mongodb import DBHelper
from models.transaction import TransactionIssue, TransactionReturn
from services.activity_service import log_activity
from utils.dates import as_utc, days_overdue, utc_now

FINE_PER_DAY = 2.0


def calculate_current_fine(transaction):
    """
    Calculate the current fine for a transaction.

    - Returned books keep their stored final fine.
    - Issued books accrue FINE_PER_DAY for every whole Asia/Kolkata calendar day
      past the due date, so a book due today carries no fine.
    - Legacy timezone-less MongoDB dates are treated as UTC.
    """
    if transaction.get("status") == "Returned":
        try:
            return float(transaction.get("fine", 0.0) or 0.0)
        except (TypeError, ValueError):
            # A legacy record with a non-numeric fine must not break the listing.
            return 0.0

    return float(days_overdue(transaction.get("due_date")) * FINE_PER_DAY)


def _find_related_member(transaction, db: DBHelper):
    """Member linked to a transaction, or None for legacy or orphaned links."""
    member_id = (transaction or {}).get("member_id")
    if not ObjectId.is_valid(member_id):
        return None
    return db.members.find_one({"_id": ObjectId(member_id)})


def issue_book(trans_in: TransactionIssue, db: DBHelper):
    if not ObjectId.is_valid(trans_in.book_id) or not ObjectId.is_valid(trans_in.member_id):
        raise HTTPException(status_code=400, detail="Invalid Book ID or Member ID")

    due_date = as_utc(trans_in.due_date)
    now = utc_now()

    # Keep this server-side check even though the Pydantic model validates it.
    if due_date <= now:
        raise HTTPException(
            status_code=400,
            detail="Due date must be in the future"
        )

    member = db.members.find_one({"_id": ObjectId(trans_in.member_id)})
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # The availability predicate and decrement must be one atomic operation.
    reservation = db.books.update_one(
        {"_id": ObjectId(trans_in.book_id), "available_quantity": {"$gt": 0}},
        {"$inc": {"available_quantity": -1}},
    )
    if reservation.matched_count == 0:
        if not db.books.find_one({"_id": ObjectId(trans_in.book_id)}):
            raise HTTPException(status_code=404, detail="Book not found")
        raise HTTPException(status_code=400, detail="Book is currently out of stock")

    trans_dict = {
        "book_id": trans_in.book_id,
        "member_id": trans_in.member_id,
        "issue_date": now,
        "due_date": due_date,
        "return_date": None,
        "fine": 0.0,
        "status": "Issued"
    }

    try:
        result = db.transactions.insert_one(trans_dict)
    except Exception as exc:
        # Compensate if persisting the transaction fails after stock is reserved.
        db.books.update_one(
            {"_id": ObjectId(trans_in.book_id)},
            {"$inc": {"available_quantity": 1}}
        )
        raise HTTPException(status_code=500, detail="Could not create transaction") from exc

    created_trans = db.transactions.find_one({"_id": result.inserted_id})
    # The issue already succeeded, so a concurrently deleted related record must
    # not turn into a 500 that makes a completed issue look like a failure.
    book = db.books.find_one({"_id": ObjectId(created_trans["book_id"])})
    member = _find_related_member(created_trans, db)
    log_activity(
        db,
        "Book Issued",
        f"{(book or {}).get('title', 'Unknown book')} issued to "
        f"{(member or {}).get('name', 'unknown member')}",
    )
    return db.serialize(created_trans)


def return_book(trans_in: TransactionReturn, db: DBHelper):
    if not ObjectId.is_valid(trans_in.transaction_id):
        raise HTTPException(status_code=400, detail="Invalid Transaction ID")

    transaction = db.transactions.find_one({"_id": ObjectId(trans_in.transaction_id)})
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.get("status") != "Issued":
        raise HTTPException(status_code=400, detail="Book already returned")

    return_date = utc_now()
    due_date = as_utc(transaction.get("due_date"))
    if due_date is None:
        raise HTTPException(status_code=500, detail="Transaction has no due date")

    book_id = transaction.get("book_id")
    if not ObjectId.is_valid(book_id):
        # Legacy or corrupted link. Refuse before touching any state so the
        # transaction and the stock count cannot drift apart.
        raise HTTPException(status_code=409, detail="The linked book record is invalid")

    # Fines accrue per whole Asia/Kolkata calendar day past the due date, so a
    # book returned on its due date carries no fine.
    fine = float(days_overdue(due_date, return_date) * FINE_PER_DAY)

    # Claim the return first; only one concurrent request can change Issued to Returned.
    returned = db.transactions.update_one(
        {"_id": ObjectId(trans_in.transaction_id), "status": "Issued"},
        {"$set": {
            "return_date": return_date,
            "fine": fine,
            "status": "Returned"
        }}
    )
    if returned.modified_count == 0:
        raise HTTPException(status_code=400, detail="Book already returned")

    restored = db.books.update_one(
        {"_id": ObjectId(book_id)},
        {"$inc": {"available_quantity": 1}},
    )
    if restored.matched_count == 0:
        # This should only occur with legacy, orphaned data. Restore the prior state.
        db.transactions.update_one(
            {"_id": ObjectId(trans_in.transaction_id), "status": "Returned"},
            {"$set": {"return_date": None, "fine": 0.0, "status": "Issued"}},
        )
        raise HTTPException(status_code=409, detail="The linked book no longer exists")

    updated_trans = db.transactions.find_one({"_id": ObjectId(trans_in.transaction_id)})
    # The return already succeeded, so a missing related record must not turn
    # into a 500 that makes a completed return look like a failure.
    book = db.books.find_one({"_id": ObjectId(book_id)})
    member = _find_related_member(updated_trans, db)
    log_activity(
        db,
        "Book Returned",
        f"{(book or {}).get('title', 'Unknown book')} returned by "
        f"{(member or {}).get('name', 'unknown member')}",
    )
    return db.serialize(updated_trans)


def get_all_transactions(db: DBHelper):
    transactions = list(db.transactions.find())
    for transaction in transactions:
        transaction["fine"] = calculate_current_fine(transaction)
    return db.serialize_list(transactions)


def get_transaction_by_id(id: str, db: DBHelper):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Transaction ID")
    transaction = db.transactions.find_one({"_id": ObjectId(id)})
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    transaction["fine"] = calculate_current_fine(transaction)
    return db.serialize(transaction)


def get_transactions_by_book(book_id: str, db: DBHelper):
    transactions = list(
        db.transactions.find({"book_id": book_id}).sort("issue_date", -1)
    )
    for transaction in transactions:
        transaction["fine"] = calculate_current_fine(transaction)
    return db.serialize_list(transactions)


def get_transactions_by_member(member_id: str, db: DBHelper):
    transactions = list(
        db.transactions.find({"member_id": member_id}).sort("issue_date", -1)
    )
    for transaction in transactions:
        transaction["fine"] = calculate_current_fine(transaction)
    return db.serialize_list(transactions)
