"""WhatsApp channel — a FastAPI router factory (engine-free).

Wraps the SementeAgent behind the WhatsApp Business API webhook. No Agno
``BaseInterface``/``AgentOS`` — the router is mounted directly on the app.
"""

from __future__ import annotations

from os import getenv
from typing import List, Optional

from fastapi.routing import APIRouter

from semente.interfaces.whatsapp.router import attach_routes


class Whatsapp:
    type = "whatsapp"

    def __init__(
        self,
        agent=None,
        prefix: str = "/whatsapp",
        tags: Optional[List[str]] = None,
        show_reasoning: bool = False,
        send_user_number_to_context: bool = False,
        access_token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        verify_token: Optional[str] = None,
        media_timeout: int = 30,
        enable_encryption: bool = False,
        encryption_key: Optional[str] = None,
    ):
        self.agent = agent
        self.prefix = prefix
        self.tags = tags or ["Whatsapp"]
        self.show_reasoning = show_reasoning
        self.send_user_number_to_context = send_user_number_to_context
        self.access_token = access_token
        self.phone_number_id = phone_number_id
        self.verify_token = verify_token
        self.media_timeout = media_timeout
        self.enable_encryption = enable_encryption

        self._encryption_key: Optional[bytes] = None
        if enable_encryption:
            raw_key = encryption_key or getenv("WHATSAPP_ENCRYPTION_KEY")
            if not raw_key:
                raise ValueError(
                    "WHATSAPP_ENCRYPTION_KEY is not set. Set the environment variable or pass encryption_key."
                )
            self._encryption_key = bytes.fromhex(raw_key)
            if len(self._encryption_key) != 32:
                raise ValueError("encryption_key must be exactly 32 bytes (64 hex chars)")

        if agent is None:
            raise ValueError("Whatsapp requires an agent")

    def get_router(self) -> APIRouter:
        router = APIRouter(prefix=self.prefix, tags=self.tags)
        return attach_routes(
            router=router,
            agent=self.agent,
            show_reasoning=self.show_reasoning,
            send_user_number_to_context=self.send_user_number_to_context,
            access_token=self.access_token,
            phone_number_id=self.phone_number_id,
            verify_token=self.verify_token,
            media_timeout=self.media_timeout,
            enable_encryption=self.enable_encryption,
            encryption_key=self._encryption_key,
        )
