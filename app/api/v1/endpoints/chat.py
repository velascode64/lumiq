"""Chat endpoint router (delegates to shared chat_service)."""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from lumiq.app.api.deps import get_chat_service

router = APIRouter()

class ChatRequest(BaseModel):
    chat_id: int
    user_id: Optional[int] = None
    text: str

class ChatReply(BaseModel):
    text: str
    parse_mode: Optional[str] = None

@router.post('/chat/message', response_model=ChatReply)
def chat_message(req: ChatRequest, chat=Depends(get_chat_service)) -> ChatReply:
    reply = chat.handle_text(req.chat_id, req.user_id or req.chat_id, req.text)
    return ChatReply(text=reply.text, parse_mode=reply.parse_mode)
