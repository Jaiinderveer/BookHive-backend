from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from database.mongodb import get_db, DBHelper
from models.user import UserCreate, UserOut, Token
from utils.jwt import get_current_user
from services import auth_service
from models.user import (
    UserCreate,
    UserOut,
    Token,
    UserUpdate,
    ProfileOut,
    ChangePassword
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserOut)
def register(user_in: UserCreate, db: DBHelper = Depends(get_db)):
    return auth_service.register_user(user_in, db)

@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: DBHelper = Depends(get_db),
):
    return auth_service.authenticate_user(form_data, db)

@router.get("/me", response_model=ProfileOut)
def me(
    current_user: dict = Depends(get_current_user),
    db: DBHelper = Depends(get_db)
):
    member = db.members.find_one({"user_id": current_user["id"]})

    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "name": member.get("name", "") if member else "",
        "email": current_user["email"],
        "phone": member.get("phone", "") if member else "",
        "address": member.get("address") if member else None,
        "role": current_user["role"]
    }
@router.put("/me", response_model=ProfileOut)
def update_me(
    user_in: UserUpdate,
    current_user: dict = Depends(get_current_user),
    db: DBHelper = Depends(get_db),
):
    return auth_service.update_profile(
        current_user["id"],
        user_in,
        db
    )
    
@router.post("/change-password")
def change_password_route(
    password_data: ChangePassword,
    current_user: dict = Depends(get_current_user),
    db: DBHelper = Depends(get_db),
):
    return auth_service.change_password(
        current_user["id"],
        password_data.current_password,
        password_data.new_password,
        db
    )