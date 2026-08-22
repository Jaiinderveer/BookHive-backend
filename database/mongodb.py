import logging

from pymongo import MongoClient, UpdateOne
from config import settings

logger = logging.getLogger(__name__)

# pymongo waits 30 seconds by default before reporting that it cannot reach a
# server. That is long enough for a platform health check to time out first, so
# a connection problem gets reported as something else entirely. These explicit
# timeouts make the real failure surface quickly.
SERVER_SELECTION_TIMEOUT_MS = 5_000
CONNECT_TIMEOUT_MS = 5_000
SOCKET_TIMEOUT_MS = 20_000


class DBHelper:
    def __init__(self):
        # connect=False keeps the constructor from starting any connection work,
        # so importing this module never touches the network. Everything that
        # needs a live server happens in initialize(), called from the FastAPI
        # lifespan handler.
        self.client = MongoClient(
            settings.MONGODB_URL,
            serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=CONNECT_TIMEOUT_MS,
            socketTimeoutMS=SOCKET_TIMEOUT_MS,
            connect=False,
        )
        self.db = self.client["bookhive"]

        # Collections
        self.users = self.db["users"]
        self.books = self.db["books"]
        self.members = self.db["members"]
        self.transactions = self.db["transactions"]
        self.activities = self.db["activities"]

    def initialize(self):
        """Prepare the database for use. Runs once at application startup.

        Called from the FastAPI lifespan handler rather than at import time: if
        MongoDB is unreachable the process must still start, otherwise no CORS
        headers are ever sent and the browser reports a backend outage as a CORS
        failure.
        """
        self.client.admin.command("ping")
        logger.info("Connected to MongoDB.")
        self._ensure_indexes()
        linked = self._link_existing_member_accounts()
        if linked:
            logger.info("Linked %d member profile(s) to a login account.", linked)
        logger.info("Database initialisation complete.")

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
        """Safely link legacy member profiles to matching member login accounts.

        Driven by the profiles that still need linking rather than by the whole
        user collection, so a database where nothing is outstanding costs two
        reads and no writes. Returns the number of profiles linked.
        """
        unlinked_filter = {"$or": [{"user_id": {"$exists": False}}, {"user_id": None}]}
        unlinked = list(self.members.find(unlinked_filter, {"_id": 1, "email": 1}))
        emails = {member["email"] for member in unlinked if member.get("email")}
        if not emails:
            return 0

        accounts = self.users.find(
            {"role": "member", "email": {"$in": list(emails)}},
            {"_id": 1, "email": 1},
        )
        user_id_by_email = {
            account["email"]: str(account["_id"])
            for account in accounts
            if account.get("email")
        }

        operations = [
            UpdateOne(
                # The unlinked condition is repeated here so a profile claimed by
                # a concurrent request is left alone.
                {"_id": member["_id"], **unlinked_filter},
                {"$set": {"user_id": user_id_by_email[member["email"]]}},
            )
            for member in unlinked
            if member.get("email") in user_id_by_email
        ]
        if not operations:
            return 0

        result = self.members.bulk_write(operations, ordered=False)
        return result.modified_count

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
