import os
import asyncio
import hashlib
from base64 import urlsafe_b64decode, urlsafe_b64encode
from time import time
from typing import Any, Literal, NamedTuple, Optional, Type, Union
from uuid import uuid4
from enum import StrEnum, auto
from dataclasses import asdict
from contextlib import suppress

import redis
import pickle

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from semente.core.orchestrator import Workflow
from semente.logging import log_error, log_info, log_warning

from semente.interfaces.whatsapp.security import validate_webhook_signature
from semente.interfaces.whatsapp.helpers import (
    WhatsAppConfig,
    download_event_media_async,
    extract_message_content,
    filter_generated_media,
    send_whatsapp_message_async,
    typing_indicator_async,
    upload_and_send_media_async,
)

_valkey_client = None


def _get_valkey_client():
    """Lazily build the Valkey/Redis client (WhatsApp debouncing).

    Only required when the WhatsApp channel is actually used; importing the
    router no longer fails when VALKEY_* env vars are absent.
    """
    global _valkey_client
    if _valkey_client is None:
        host = os.getenv("VALKEY_HOST")
        port = os.getenv("VALKEY_PORT")
        db = os.getenv("VALKEY_DB")
        if not (host and port and db):
            raise ValueError(
                "VALKEY_HOST, VALKEY_PORT and VALKEY_DB environment variables "
                "must be set for the WhatsApp channel."
            )
        _valkey_client = redis.Redis(
            host=host, port=int(port), db=int(db), decode_responses=True
        )
    return _valkey_client

_LONG_SLEEP = 8
_SHORT_SLEEP = 4

_EXECUTION_MESSAGE = "Ainda estamos processando sua última mensagem. Por favor, aguarde..."
_ERROR_MESSAGE = "Desculpe, ocorreu um erro ao processar sua mensagem. Por favor, tente novamente mais tarde."
_SESSION_RESET_MESSAGE = "Nova conversa iniciada!"

# Metadata lines from ReasoningTools that aren't useful to end users
_REASONING_SKIP_PREFIXES = ("Action:", "Next Action:", "Confidence:")

# WhatsApp tools that send messages directly during agent execution;
# router skips duplicate text when any of these ran
_WA_TOOL_NAMES = frozenset(
    {
        "send_text_message",
        "send_template_message",
        "send_reply_buttons",
        "send_list_message",
        "send_image",
        "send_document",
        "send_location",
        "send_reaction",
    }
)


class _SessionConfig(NamedTuple):
    store: Any
    has_db: bool


class _DebouceStatus(StrEnum):
    PENDING: str = auto()
    COMPLETE: str = auto()


def _resolve_session_config(workflow: Workflow) -> _SessionConfig:
    store = getattr(workflow, "store", None)
    return _SessionConfig(store=store, has_db=store is not None)


def _format_reasoning(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped in ("—", "---"):
            continue
        if stripped.startswith(_REASONING_SKIP_PREFIXES):
            continue
        lines.append(stripped)
    return "\n".join(lines)


class WhatsAppWebhookResponse(BaseModel):
    status: str = Field(default="ok", description="Processing status")


def _encrypt_phone(phone: str, key: bytes) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise ImportError("`cryptography` not installed. Please install using `pip install cryptography`")
    # Same phone → same nonce → same ciphertext; safe because identical plaintext
    nonce = hashlib.sha256(phone.encode()).digest()[:12]
    ct = AESGCM(key).encrypt(nonce, phone.encode(), None)
    return urlsafe_b64encode(nonce + ct).decode()


def decrypt_phone(token: str, key: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = urlsafe_b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def attach_routes(
    router: APIRouter,
    workflow: Workflow = None,
    show_reasoning: bool = False,
    send_user_number_to_context: bool = False,
    access_token: Optional[str] = None,
    phone_number_id: Optional[str] = None,
    verify_token: Optional[str] = None,
    media_timeout: int = 30,
    enable_encryption: bool = False,
    encryption_key: Optional[bytes] = None,
) -> APIRouter:
    if workflow is None:
        raise ValueError("A workflow must be provided.")

    # Inner functions capture config via closure to keep each instance isolated
    entity = workflow
    entity_name = getattr(entity, "name", "workflow")
    # entity_name labels messages; entity_id namespaces session IDs
    op_suffix = entity_name.lower().replace(" ", "_")
    entity_id = entity_name

    # Used by /new handler (create sessions) and process_message (find latest)
    session_config = _resolve_session_config(entity)

    config = WhatsAppConfig.init(
        access_token=access_token,
        phone_number_id=phone_number_id,
        verify_token=verify_token,
        media_timeout=media_timeout,
    )

    @router.get("/status", operation_id=f"whatsapp_status_{op_suffix}")
    async def status():
        return {"status": "available"}

    @router.get(
        "/webhook",
        operation_id=f"whatsapp_verify_{op_suffix}",
        name="whatsapp_verify",
        description="Handle WhatsApp webhook verification",
    )
    async def verify_webhook(request: Request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        if not config.verify_token:
            raise HTTPException(status_code=500, detail="WHATSAPP_VERIFY_TOKEN is not set")

        if mode == "subscribe" and token == config.verify_token:
            if not challenge:
                raise HTTPException(status_code=400, detail="No challenge received")
            return PlainTextResponse(content=challenge)

        raise HTTPException(status_code=403, detail="Invalid verify token or mode")

    @router.post(
        "/webhook",
        operation_id=f"whatsapp_webhook_{op_suffix}",
        name="whatsapp_webhook",
        description="Process incoming WhatsApp messages",
        response_model=WhatsAppWebhookResponse,
        responses={
            200: {"description": "Event processed successfully"},
            403: {"description": "Invalid webhook signature"},
        },
    )
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        payload = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")

        if not validate_webhook_signature(payload, signature):
            log_warning("Invalid webhook signature")
            raise HTTPException(status_code=403, detail="Invalid signature")

        body = await request.json()

        if body.get("object") != "whatsapp_business_account":
            log_warning(f"Received non-WhatsApp webhook object: {body.get('object')}")
            return WhatsAppWebhookResponse(status="ignored")

        # ACK immediately, process in background. Meta retries if no 200 within ~20s
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for message in change.get("value", {}).get("messages", []):
                    background_tasks.add_task(process_message, message)

        return WhatsAppWebhookResponse(status="processing")

    # TODO: Criar um buffer para mensagens pós valkey_execution_lock.
    async def process_message(message: dict):
        # Extract early so error handler can notify the user
        phone_number = message.get("from")
        if not phone_number:
            log_warning("Message missing 'from' field, skipping")
            return
        # Splits identity: user_id (possibly encrypted) for DB storage, phone_number (raw) for API sends
        user_id = _encrypt_phone(phone_number, encryption_key) if enable_encryption and encryption_key else phone_number
        timestamp: str = message.get("timestamp")
        try:   
            message_id = message.get("id")
            await typing_indicator_async(message_id, config)

            parsed = extract_message_content(message)
            if parsed is None:
                msg_type = message.get("type", "unknown")
                # "unsupported" is WhatsApp's label for stickers and other rich types
                label = "this message type" if msg_type == "unsupported" else msg_type.title()
                await send_whatsapp_message_async(phone_number, f"Sorry, {label} is not supported yet.", config)
                return
            
            valkey_execution_lock = _get_valkey_client().lock(f"debounce_lock:{user_id}", timeout=60, blocking=True, blocking_timeout=5)
            if not valkey_execution_lock.acquire():
                log_info("Dropping message! Execution already in cursor...")
                await send_whatsapp_message_async(phone_number, _EXECUTION_MESSAGE, config) 
                return
                
            _get_valkey_client().hset(f"debounce_status:{user_id}", timestamp, _DebouceStatus.PENDING.value)
            old_ts = _get_valkey_client().get(f"debounce_ts:{user_id}")
            
            if not old_ts or int(old_ts) <= int(timestamp):
                _get_valkey_client().set(f"debounce_ts:{user_id}", timestamp)

            # /new starts a fresh session — old session data is preserved
            if parsed.text.strip().lower() == "/new":
                if not session_config.has_db:
                    await send_whatsapp_message_async(
                        phone_number, "Session reset requires storage to be configured.", config
                    )
                    _get_valkey_client().delete(f"debounce_status:{user_id}", f"debounce_msgs:{user_id}")
                    return
                try:
                    new_session_id = f"wa:{entity_id}:{user_id}:{uuid4().hex[:8]}"
                    session_config.store.save(user_id, new_session_id, session_state={}, runs=[])
                    await send_whatsapp_message_async(phone_number, _SESSION_RESET_MESSAGE, config)
                except Exception as e:
                    log_warning(f"Failed to persist /new session: {e}")
                    await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config)

                _get_valkey_client().delete(f"debounce_status:{user_id}", f"debounce_msgs:{user_id}")
                return
            
            valkey_execution_lock.release()

            log_info(f"\033[32mProcessing message from {user_id[:12]}: {parsed.text}\033[0m")

            # Resolve session: check DB for latest, fall back to deterministic ID
            default_session_id = f"wa:{entity_id}:{user_id}"
            session_id = default_session_id
            if session_config.has_db:
                try:
                    sessions = session_config.store.list_sessions(user_id)
                    if sessions:
                        session_id = sessions[0]
                except Exception as e:
                    log_warning(f"Session lookup failed, using default: {e}")

            # Download media from Meta servers and wrap as Agno media objects
            media_kwargs, skipped_media = await download_event_media_async(parsed, config)

            msg_data = {
                "parsed": asdict(parsed),
                "media_kwargs": media_kwargs,
                "skipped_media": skipped_media,
                "timestamp": timestamp,
            }

            _get_valkey_client().rpush(f"debounce_msgs:{user_id}", pickle.dumps(msg_data).hex())
            _get_valkey_client().hset(f"debounce_status:{user_id}", timestamp, _DebouceStatus.COMPLETE.value)
            
            log_info(f"Process {timestamp} went to sleep!")
            await asyncio.sleep(_LONG_SLEEP if (message.get("type") == "image" and not message.get("caption")) else _SHORT_SLEEP)
            
            log_info(f"Process {timestamp} woke up!")
            if not valkey_execution_lock.acquire():
                return
            
            latest_ts = _get_valkey_client().get(f"debounce_ts:{user_id}")
            if latest_ts and latest_ts != timestamp:
                log_info(f"Dropping process {timestamp}, not the latest: {latest_ts}...")
                valkey_execution_lock.release()
                return
            log_info("Executing process!")

            wait_loops = 0
            while wait_loops < 30:
                statuses = _get_valkey_client().hvals(f"debounce_status:{user_id}")
                if not any([_DebouceStatus(s) == _DebouceStatus.PENDING for s in statuses]):
                    break
                await asyncio.sleep(1)
                wait_loops += 1
            _get_valkey_client().delete(f"debounce_status:{user_id}")
            
            raw_msgs = _get_valkey_client().lrange(f"debounce_msgs:{user_id}", 0, -1)
            _get_valkey_client().delete(f"debounce_msgs:{user_id}")

            all_msgs = sorted([pickle.loads(bytes.fromhex(m)) for m in raw_msgs], key=lambda x: int(x["timestamp"]))

            final_text = ""
            run_kwargs = {"user_id": user_id,"session_id": session_id}
            for msg_item in all_msgs:
                final_text += msg_item.get("parsed", {}).get("text", "") + "\n"
                for key, val in msg_item.get("media_kwargs", {}).items():
                    run_kwargs[key] = run_kwargs.get(key, []) + val

            # Prepend skip notice so the agent (and user) knows media was dropped
            if skipped_media:
                notice = "[Some media could not be downloaded: " + "; ".join(skipped_media) + "]\n\n"
                final_text = notice + final_text

            if send_user_number_to_context:
                # ponytail: semente workflow has no dependencies concept; ignored for now.
                pass

            # Refresh typing indicator every 20s while the agent runs
            # WhatsApp auto-dismisses the indicator after ~25s
            async def _keep_typing():
                try:
                    while True:
                        await asyncio.sleep(20)
                        await typing_indicator_async(message_id, config)
                except asyncio.CancelledError:
                    pass

            typing_task = asyncio.create_task(_keep_typing())
            try:
                log_warning(f"Running workflow! Kwargs:\n{run_kwargs}")
                response = await asyncio.to_thread(entity.run, input=final_text, **run_kwargs)
            finally:
                typing_task.cancel()

            # Engines may echo run-input media back in the response; only send
            # media the workflow actually generated (TTS, agent images, ...)
            for attr, media_type in (
                ("images", "image"),
                ("videos", "video"),
                ("files", "document"),
                ("audio", "audio"),
            ):
                items = filter_generated_media(response, run_kwargs).get(attr)
                if items:
                    await upload_and_send_media_async(items, media_type, phone_number, config)

            if response.content:
                await send_whatsapp_message_async(phone_number, response.content, config)

        except Exception as e:
            log_error(f"Error processing message: {e}")
            try:
                await send_whatsapp_message_async(phone_number, _ERROR_MESSAGE, config)
            except Exception as send_error:
                log_error(f"Error sending error message: {send_error}")
        finally:
            if valkey_execution_lock.locked():
                with suppress(Exception):
                    valkey_execution_lock.release()

    return router