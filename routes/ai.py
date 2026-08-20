from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from database.mongodb import get_db, DBHelper
from utils.jwt import get_current_librarian
from services import ai_service

router = APIRouter(prefix="/api/ai", tags=["AI Assistant"])


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None


@router.post("/chat")
def chat(
    request: ChatRequest,
    db: DBHelper = Depends(get_db),
    current_user: dict = Depends(get_current_librarian),
):
    if not request.message.strip():
        return {"reply": "Please provide a message."}
    return ai_service.process_chat(request.message, db, [h.model_dump() for h in (request.history or [])])
