import datetime
from database.mongodb import DBHelper

def log_activity(db, activity_type: str, details: str):
    try:
        activity = {
            "type": activity_type,
            "details": details,
            "timestamp": datetime.datetime.utcnow()
        }
        db.activities.insert_one(activity)
    except Exception as e:
        print(f"[Activity] Failed to log activity: {e}")
        
def get_recent_activities(db: DBHelper, limit: int = 10):
    activities = db.activities.find().sort("timestamp", -1).limit(limit)
    return db.serialize_list(activities)
