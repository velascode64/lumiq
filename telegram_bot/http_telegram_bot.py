"""
Telegram polling client that forwards messages to Lumiq Core API.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Dict, List, Optional, Set

import requests


logger = logging.getLogger(__name__)


class ApiTelegramBot:
    def __init__(self, telegram_token: str, core_api_base_url: str):
        self.telegram_token = telegram_token
        self.base_url = f"https://api.telegram.org/bot{telegram_token}"
        self.core_api_base_url = core_api_base_url.rstrip("/")
        self.core_timeout_seconds = float(os.getenv("LUMIQ_CORE_REQUEST_TIMEOUT_SECONDS", "300"))
        self.fast_path_seconds = float(os.getenv("LUMIQ_TELEGRAM_FAST_PATH_SECONDS", "10"))
        self.async_workers = max(int(os.getenv("LUMIQ_TELEGRAM_ASYNC_WORKERS", "4")), 1)
        self._executor = ThreadPoolExecutor(max_workers=self.async_workers, thread_name_prefix="telegram-core")
        self._core_executor = ThreadPoolExecutor(max_workers=self.async_workers, thread_name_prefix="telegram-core-call")
        self._inflight_lock = threading.Lock()
        self._inflight: Set[Future] = set()

    def _telegram_post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(f"{self.base_url}/{method}", json=payload, timeout=45)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error on {method}: {data}")
        return data

    def _api_get_updates(self, offset: Optional[int]) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {"timeout": 30, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        data = self._telegram_post("getUpdates", payload)
        return data.get("result", [])

    def _send_message(self, chat_id: int, text: str, parse_mode: Optional[str] = None) -> None:
        chunks = [text[i : i + 3900] for i in range(0, len(text), 3900)] or ["(empty)"]
        for chunk in chunks:
            payload: Dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            try:
                self._telegram_post("sendMessage", payload)
            except Exception:
                if "parse_mode" in payload:
                    payload.pop("parse_mode", None)
                    self._telegram_post("sendMessage", payload)
                else:
                    raise

    def _send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        try:
            self._telegram_post("sendChatAction", {"chat_id": chat_id, "action": action})
        except Exception:
            logger.debug("Failed to send chat action", exc_info=True)

    @contextmanager
    def _typing_indicator(self, chat_id: int):
        stop_event = threading.Event()

        def _worker() -> None:
            while not stop_event.is_set():
                self._send_chat_action(chat_id, action="typing")
                stop_event.wait(4.0)

        thread = threading.Thread(target=_worker, name=f"telegram-typing-{chat_id}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1.0)

    def _forward_to_core(self, chat_id: int, user_id: int, text: str) -> Dict[str, Any]:
        response = requests.post(
            f"{self.core_api_base_url}/chat/message",
            json={"chat_id": chat_id, "user_id": user_id, "text": text},
            timeout=self.core_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def _on_future_done(self, future: Future) -> None:
        with self._inflight_lock:
            self._inflight.discard(future)

    def _process_message_async(self, chat_id: int, user_id: int, text: str) -> None:
        start = time.monotonic()
        logger.info("Async chat task start | chat_id=%s | user_id=%s | text=%s", chat_id, user_id, text)
        try:
            with self._typing_indicator(chat_id):
                core_future = self._core_executor.submit(self._forward_to_core, chat_id, user_id, text)
                try:
                    reply = core_future.result(timeout=self.fast_path_seconds)
                    logger.info("Async chat task fast-path | chat_id=%s | threshold=%.2fs", chat_id, self.fast_path_seconds)
                except FutureTimeoutError:
                    self._send_message(
                        chat_id=chat_id,
                        text="Procesando tu solicitud... te envio la respuesta en breve.",
                    )
                    logger.info("Async chat task slow-path | chat_id=%s | threshold=%.2fs", chat_id, self.fast_path_seconds)
                    reply = core_future.result()
            self._send_message(chat_id=chat_id, text=reply.get("text", ""), parse_mode=reply.get("parse_mode"))
            elapsed = time.monotonic() - start
            logger.info("Async chat task done | chat_id=%s | elapsed=%.2fs", chat_id, elapsed)
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.exception("Async chat task failed | chat_id=%s | elapsed=%.2fs | err=%s", chat_id, elapsed, exc)
            self._send_message(
                chat_id=chat_id,
                text=(
                    "No pude completar tu solicitud a tiempo. "
                    "Intenta de nuevo con una consulta mas corta o en unos segundos."
                ),
            )

    def _submit_async_task(self, chat_id: int, user_id: int, text: str) -> None:
        future = self._executor.submit(self._process_message_async, chat_id, user_id, text)
        with self._inflight_lock:
            self._inflight.add(future)
        future.add_done_callback(self._on_future_done)

    def _handle_update(self, update: Dict[str, Any]) -> None:
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        if not text:
            return

        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        chat_id = chat.get("id")
        user_id = sender.get("id", chat_id)
        if chat_id is None:
            return

        chat_id_int = int(chat_id)
        user_id_int = int(user_id or chat_id)
        self._submit_async_task(chat_id=chat_id_int, user_id=user_id_int, text=text)

    def run(self) -> None:
        logger.info("Starting Telegram polling client (Core API: %s)", self.core_api_base_url)
        offset: Optional[int] = None
        while True:
            try:
                updates = self._api_get_updates(offset)
                for update in updates:
                    offset = update["update_id"] + 1
                    self._handle_update(update)
            except KeyboardInterrupt:
                logger.info("Telegram client stopped by user")
                break
            except Exception as exc:
                logger.exception("Telegram polling client error: %s", exc)
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._core_executor.shutdown(wait=False, cancel_futures=True)
