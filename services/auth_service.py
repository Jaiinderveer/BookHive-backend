from fastapi import HTTPException, status
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from datetime import timedelta
from datetime import datetime
from database.mongodb import DBHelper
from models.user import UserCreate
from services.member_service import generate_membership_id
from utils.jwt import get_password_hash, verify_password, create_access_token
from config import settings
from models.user import UserCreate, UserUpdate
def change_password(
    user_id: str,
    current_password: str,
    new_password: str,
    db: DBHelper
):
    try:
        user_object_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    user = db.users.find_one({"_id": user_object_id})

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if not verify_password(current_password, user["password"]):
        raise HTTPException(
            status_code=400,
            detail="Current password is incorrect"
        )

    hashed_password = get_password_hash(new_password)

    db.users.update_one(
        {"_id": user_object_id},
        {"$set": {"password": hashed_password}}
    )

    return {"message": "Password changed successfully"}
def update_profile(user_id: str, user_in: UserUpdate, db: DBHelper):
    try:
        user_object_id = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user ID")

    user = db.users.find_one({"_id": user_object_id})

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_in.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(status_code=400, detail="No changes provided")

    # If email is being changed, make sure another user isn't already using it
    if "email" in update_data:
        existing_user = db.users.find_one({
            "email": update_data["email"],
            "_id": {"$ne": user_object_id}
        })

        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="Email already registered"
            )

    # Fields stored in users
    user_update = {}

    if "email" in update_data:
        user_update["email"] = update_data["email"]

    if user_update:
        db.users.update_one(
            {"_id": user_object_id},
            {"$set": user_update}
        )

    # Fields stored in members
    member_update = {}

    for field in ["name", "email", "phone", "address"]:
        if field in update_data:
            member_update[field] = update_data[field]

    if member_update:
        db.members.update_one(
            {"user_id": user_id},
            {"$set": member_update}
        )

    # Fetch updated data
    updated_user = db.users.find_one({"_id": user_object_id})
    member = db.members.find_one({"user_id": user_id})

    return {
        "id": str(updated_user["_id"]),
        "username": updated_user["username"],
        "name": member.get("name", ""),
        "email": updated_user["email"],
        "phone": member.get("phone", ""),
        "address": member.get("address"),
        "role": updated_user.get("role", "member")
    }
def register_user(user_in: UserCreate, db: DBHelper):
    if db.users.find_one({"username": user_in.username}):
        raise HTTPException(status_code=400, detail="Username already registered")
    
    if db.users.find_one({"email": user_in.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    user_dict = user_in.model_dump(exclude={"name", "phone", "address"})
    # Always force member role on registration — librarian accounts are assigned by admins.
    user_dict["role"] = "member"
    user_dict["password"] = get_password_hash(user_dict["password"])
    
    try:
        result = db.users.insert_one(user_dict)
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="Username or email already registered")
    # A login account and a borrower profile are linked by user_id. If an
    # administrator created the profile first, registration adopts it by email.
    existing_member = db.members.find_one({"email": user_in.email})
    if existing_member:
        db.members.update_one(
            {"_id": existing_member["_id"]},
            {"$set": {"user_id": str(result.inserted_id)}},
        )
    else:
        try:
            db.members.insert_one({
                "user_id": str(result.inserted_id),
                "name": user_in.name,
                "email": user_in.email,
                "phone": user_in.phone,
                "address": user_in.address,
                "membership_id": generate_membership_id(db),
                "created_at": datetime.utcnow(),
            })
        except DuplicateKeyError as exc:
            db.users.delete_one({"_id": result.inserted_id})
            raise HTTPException(status_code=400, detail="Membership ID already exists") from exc

    created_user = db.users.find_one({"_id": result.inserted_id})
    return db.serialize(created_user)

def authenticate_user(form_data, db: DBHelper):
    user = db.users.find_one({"username": form_data.username}) or db.users.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_role = str(user.get("role", "member")).lower()
    user_id = str(user["_id"])
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"], "id": user_id, "role": user_role},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
