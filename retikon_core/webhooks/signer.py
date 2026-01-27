from __future__ import annotations

import hashlib
import hmac


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    message = f"{timestamp}.".encode("utf-8") + body
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"
