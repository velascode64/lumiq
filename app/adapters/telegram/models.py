"""Telegram adapter DTO placeholders (transitional)."""
from dataclasses import dataclass
from typing import Optional

@dataclass
class TelegramMessage:
    chat_id: int
    user_id: int
    text: str
    parse_mode: Optional[str] = None
