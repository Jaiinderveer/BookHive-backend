from bson import ObjectId
from database.mongodb import DBHelper
from services.activity_service import get_recent_activities
from utils.dates import start_of_today_utc

def get_dashboard_metrics(db: DBHelper):
    total_members = db.members.count_documents({})
    
    pipeline_books = [
        {"$group": {
            "_id": None, 
            "total_books": {"$sum": "$quantity"},
            "books_available": {"$sum": "$available_quantity"}
        }}
    ]
    books_agg = list(db.books.aggregate(pipeline_books))
    if books_agg:
        total_books = books_agg[0].get("total_books", 0)
        books_available = books_agg[0].get("books_available", 0)
    else:
        total_books = 0
        books_available = 0

    books_issued = db.transactions.count_documents({"status": "Issued"})

    # Local midnight in the library timezone, expressed as the UTC instant that
    # MongoDB stores. Both metrics below are calendar rules, not elapsed-time
    # rules, so they must pivot on the local day boundary rather than on UTC.
    start_of_today = start_of_today_utc()

    # A book is overdue only once the local calendar date is past its due date,
    # which is exactly a due date falling before local midnight today. This
    # matches the fine calculation, so anything due today is not counted.
    overdue_books = db.transactions.count_documents({
        "status": "Issued",
        "due_date": {"$lt": start_of_today}
    })

    today_transactions = db.transactions.count_documents({
        "$or": [
            {"issue_date": {"$gte": start_of_today}},
            {"return_date": {"$gte": start_of_today}}
        ]
    })

    # Activities
    activities = get_recent_activities(db)

    # Smart Insights
    insights = []
    
    # Low stock
    low_stock_books = list(db.books.find({"available_quantity": {"$lt": 5, "$gt": 0}}).limit(3))
    for book in low_stock_books:
        # Legacy or imported books may be missing a title or a numeric count.
        # Skip those rather than failing the whole dashboard.
        title = book.get("title")
        available = book.get("available_quantity")
        if title and isinstance(available, int):
            insights.append(f"Only {available} copies of {title} remain.")

    # Overdue
    if overdue_books > 0:
        insights.append(f"{overdue_books} books are overdue.")

    # Issued today
    today_issued = db.transactions.count_documents({"issue_date": {"$gte": start_of_today}})
    if today_issued > 0:
        insights.append(f"{today_issued} books were issued today.")

    # Unpaid fines
    members_with_fines = list(db.transactions.find({"status": "Returned", "fine": {"$gt": 0}}).limit(3))
    for trans in members_with_fines:
        # Legacy or imported transactions may carry a missing or non-ObjectId
        # member_id. Skip those rather than failing the whole dashboard.
        raw_member_id = trans.get("member_id")
        if isinstance(raw_member_id, ObjectId):
            member_key = raw_member_id
        elif ObjectId.is_valid(raw_member_id):
            member_key = ObjectId(raw_member_id)
        else:
            continue
        member = db.members.find_one({"_id": member_key})
        if member and member.get("name"):
            insights.append(f"{member['name']} has unpaid fines.")

    return {
        "total_books": total_books,
        "total_members": total_members,
        "books_issued": books_issued,
        "books_available": books_available,
        "overdue_books": overdue_books,
        "today_transactions": today_transactions,
        "activities": activities,
        "insights": insights
    }
