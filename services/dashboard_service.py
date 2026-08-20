from datetime import datetime
from bson import ObjectId
from database.mongodb import DBHelper
from services.activity_service import get_recent_activities

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

    now = datetime.utcnow()
    overdue_books = db.transactions.count_documents({
        "status": "Issued",
        "due_date": {"$lt": now}
    })

    start_of_today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
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
        insights.append(f"Only {book['available_quantity']} copies of {book['title']} remain.")

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
        member = db.members.find_one({"_id": trans["member_id"] if isinstance(trans["member_id"], ObjectId) else ObjectId(trans["member_id"])})
        if member:
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
