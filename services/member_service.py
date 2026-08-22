from fastapi import HTTPException
from bson import ObjectId
from pymongo.errors import DuplicateKeyError
from datetime import datetime
from database.mongodb import DBHelper
from models.member import MemberCreate, MemberUpdate, MemberAccountCreate
from utils.jwt import get_password_hash
from services.activity_service import log_activity


def generate_membership_id(db: DBHelper) -> str:
    while True:
        membership_id = f"BH-{ObjectId()}"
        if not db.members.find_one({"membership_id": membership_id}):
            return membership_id


def create_member(member_in: MemberCreate, db: DBHelper):
    if db.users.find_one({"username": member_in.username}) or db.users.find_one({"email": member_in.email}):
        raise HTTPException(status_code=400, detail="Username or email already registered")

    user_result = db.users.insert_one({
        "username": member_in.username,
        "email": member_in.email,
        "password": get_password_hash(member_in.password),
        "role": "member",
    })
    member_dict = member_in.model_dump(exclude={"username", "password"})
    member_dict["membership_id"] = generate_membership_id(db)
    member_dict["user_id"] = str(user_result.inserted_id)
    member_dict["created_at"] = datetime.utcnow()
    
    try:
        result = db.members.insert_one(member_dict)
    except DuplicateKeyError:
        db.users.delete_one({"_id": user_result.inserted_id})
        raise HTTPException(status_code=400, detail="A member with this email or membership ID already exists")
    created_member = db.members.find_one({"_id": result.inserted_id})
    log_activity(db, "Member Registered", f"Member {created_member['name']} registered")
    return db.serialize(created_member)

def get_all_members(db: DBHelper):
    members = db.members.find()
    return db.serialize_list(members)

def get_member_by_id(id: str, db: DBHelper):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Member ID")
    
    member = db.members.find_one({"_id": ObjectId(id)})
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    return db.serialize(member)

def create_member_account(id: str, account_in: MemberAccountCreate, db: DBHelper):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Member ID")
    member = db.members.find_one({"_id": ObjectId(id)})
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.get("user_id"):
        raise HTTPException(status_code=409, detail="This member already has a login account")
    if db.users.find_one({"username": account_in.username}) or db.users.find_one({"email": member["email"]}):
        raise HTTPException(status_code=400, detail="Username or email already registered")

    user_result = db.users.insert_one({
        "username": account_in.username,
        "email": member["email"],
        "password": get_password_hash(account_in.password),
        "role": "member",
    })
    db.members.update_one({"_id": member["_id"]}, {"$set": {"user_id": str(user_result.inserted_id)}})
    return db.serialize(db.members.find_one({"_id": member["_id"]}))

def update_member(id: str, member_in: MemberUpdate, db: DBHelper):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Member ID")

    supplied = member_in.model_dump(exclude_unset=True)

    # name, email and phone are required on a member, so a null there means
    # "leave this field as it is". address is optional, so an explicitly supplied
    # null or blank value clears it rather than being dropped.
    update_data = {
        key: value
        for key, value in supplied.items()
        if key != "address" and value is not None
    }
    if "address" in supplied:
        address = supplied["address"]
        update_data["address"] = address.strip() or None if isinstance(address, str) else None

    if not update_data:
        raise HTTPException(status_code=400, detail="No data provided to update")

    member = db.members.find_one({"_id": ObjectId(id)})
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if "email" in update_data and member.get("user_id"):
        existing_user = db.users.find_one({"email": update_data["email"], "_id": {"$ne": ObjectId(member["user_id"])}})
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
    try:
        result = db.members.update_one({"_id": ObjectId(id)}, {"$set": update_data})
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="A member with this email already exists")
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Member not found")
    if "email" in update_data and member.get("user_id") and ObjectId.is_valid(member["user_id"]):
        db.users.update_one({"_id": ObjectId(member["user_id"])}, {"$set": {"email": update_data["email"]}})
        
    updated_member = db.members.find_one({"_id": ObjectId(id)})
    log_activity(db, "Member Updated", f"{updated_member.get('name', 'Member')} details updated")
    return db.serialize(updated_member)

def delete_member(id: str, db: DBHelper):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Invalid Member ID")
        
    if db.transactions.count_documents({"member_id": id}) > 0:
        raise HTTPException(status_code=409, detail="Cannot delete a member with transaction history")
    member = db.members.find_one({"_id": ObjectId(id)})
    result = db.members.delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Member not found")
    if member and ObjectId.is_valid(member.get("user_id", "")):
        db.users.delete_one({"_id": ObjectId(member["user_id"])})
    return {"detail": "Member deleted successfully"}
