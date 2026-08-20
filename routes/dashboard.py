from fastapi import APIRouter, Depends
from database.mongodb import get_db, DBHelper
from utils.jwt import get_current_librarian
from services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/")
def get_dashboard_metrics(db: DBHelper = Depends(get_db), current_user: dict = Depends(get_current_librarian)):
    return dashboard_service.get_dashboard_metrics(db)
