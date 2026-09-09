"""Web Push delivery: VAPID keys on disk, pywebpush for the wire protocol.

The VAPID keypair is generated once into {STORAGE_DIR}/vapid.json and reused —
the public key is handed to browsers as applicationServerKey, the private key
never leaves the server. Expired subscriptions (HTTP 404/410 from the push
service) are deleted on send.
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import PushSubscription, User
from ..storage import STORAGE_DIR

log = logging.getLogger(__name__)

VAPID_PATH = STORAGE_DIR / "vapid.json"


def _vapid() -> dict:
    """Load or create the VAPID keypair. Returns {"private_pem", "public_key"}."""
    if VAPID_PATH.exists():
        return json.loads(VAPID_PATH.read_text())
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid
    from py_vapid.utils import b64urlencode

    vapid = Vapid()
    vapid.generate_keys()
    keys = {
        "private_pem": vapid.private_pem().decode(),
        "public_key": b64urlencode(vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)),
    }
    VAPID_PATH.parent.mkdir(parents=True, exist_ok=True)
    VAPID_PATH.write_text(json.dumps(keys, indent=2))
    return keys


def public_key() -> str:
    return _vapid()["public_key"]


def _send_one(sub: PushSubscription, payload: dict) -> str:
    """Synchronous send (run via asyncio.to_thread). Returns sent|expired|error."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": sub.keys},
            data=json.dumps(payload),
            vapid_private_key=_vapid()["private_pem"],
            vapid_claims={"sub": get_settings().vapid_sub},
            timeout=15,
        )
        return "sent"
    except WebPushException as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (404, 410):
            return "expired"
        log.warning("web push failed (status=%s): %s", status, exc)
        return "error"
    except Exception as exc:  # network down, malformed endpoint, ...
        log.warning("web push failed: %s", exc)
        return "error"


async def send_to_user(db: AsyncSession, user: User, title: str, body: str, url: str = "/today") -> int:
    """Send a notification to every subscription of the user. Returns sent count."""
    subs = (await db.execute(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    )).scalars().all()
    sent = 0
    for sub in subs:
        outcome = await asyncio.to_thread(_send_one, sub, {"title": title, "body": body, "url": url})
        if outcome == "sent":
            sent += 1
        elif outcome == "expired":
            await db.delete(sub)
    return sent
