from pymongo import MongoClient
from config import settings

class DBHelper:
    def __init__(self):
        self.client = MongoClient(settings.MONGODB_URL)
        self.db = self.client["bookhive"]
        
        # Collections
        self.users = self.db["users"]
        self.books = self.db["books"]
        self.members = self.db["members"]
        self.transactions = self.db["transactions"]
        self.activities = self.db["activities"]
        self._ensure_indexes()
        self._link_existing_member_accounts()

    def _ensure_indexes(self):
        """Enforce identifiers that must remain unique even under concurrent requests."""
        self.users.create_index("username", unique=True)
        self.users.create_index("email", unique=True)
        self.books.create_index("isbn", unique=True)
        self.members.create_index("membership_id", unique=True)
        self.members.create_index("email", unique=True)
        self.members.create_index("user_id", unique=True, sparse=True)
        self.transactions.create_index([("book_id", 1), ("status", 1)])
        self.transactions.create_index([("member_id", 1), ("status", 1)])
        self.activities.create_index("timestamp")

    def _link_existing_member_accounts(self):
        """Safely link legacy member profiles to matching member login accounts."""
        for user in self.users.find({"role": "member"}, {"_id": 1, "email": 1}):
            email = user.get("email")
            if email:
                self.members.update_many(
                    {"email": email, "$or": [{"user_id": {"$exists": False}}, {"user_id": None}]},
                    {"$set": {"user_id": str(user["_id"])}},
                )

    def serialize(self, doc):
        """Helper function to stringify MongoDB ObjectIds."""
        if doc is None:
            return None
        doc["id"] = str(doc["_id"])
        del doc["_id"]
        return doc

    def serialize_list(self, docs):
        return [self.serialize(doc) for doc in docs]

db_helper = DBHelper()

def get_db():
    return db_helper
