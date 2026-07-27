"""
Auth: Telegram Login Widget verification + simple username/password +
a signed session cookie.

Design intent: the app is for 2-4 users. Telegram login is optional.
Users can also register/login with a simple username + password on the
website directly. The allow-list still gates Telegram logins, but web
accounts are open to anyone who can reach the site.
"""
import hashlib
import hmac
import os
import time
import json
import base64

SECRET_KEY = os.environ.get("SECRET_KEY", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ALLOWED_IDS = {
    int(x) for x in os.environ.get("ALLOWED_IDS", "").replace(" ", "").split(",") if x
}
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
TELEGRAM_AUTH_FRESHNESS = 60 * 60 * 24  # 24h, per Telegram's own recommendation

_PLACEHOLDER_SECRETS = {"", "change-me-in-production", "changeme", "secret"}


def assert_secret_key_is_safe():
    """
    Called once at startup. Refuses to boot with a missing/placeholder
    SECRET_KEY instead of silently signing session cookies with something
    guessable -- that key is what makes the session cookie unforgeable.
    """
    if SECRET_KEY.strip().lower() in _PLACEHOLDER_SECRETS or len(SECRET_KEY) < 32:
        raise RuntimeError(
            "SECRET_KEY is unset, a placeholder, or too short (<32 chars). "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\" "
            "and put it in your .env file before starting the server."
        )


def verify_telegram_login(auth_data: dict) -> bool:
    """
    Verifies the hash Telegram's Login Widget sends, per:
    https://core.telegram.org/widgets/login#checking-authorization

    Also enforces the 24h auth_date freshness window so an old, previously
    valid payload can't be replayed indefinitely.
    """
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured")

    data = dict(auth_data)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return False

    auth_date = data.get("auth_date")
    try:
        if auth_date is None or (time.time() - int(auth_date)) > TELEGRAM_AUTH_FRESHNESS:
            return False
    except (TypeError, ValueError):
        return False

    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    computed_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    return hmac.compare_digest(computed_hash, received_hash)


def is_allowed(telegram_id: int) -> bool:
    return telegram_id in ALLOWED_IDS


# ---------- session cookie: HMAC-signed, no server-side session store needed ----------

def create_session_token(telegram_id: int) -> str:
    payload = {"telegram_id": telegram_id, "issued_at": int(time.time())}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session_token(token: str) -> int | None:
    """Returns user_id if the token is valid and unexpired. Telegram users must still be allow-listed."""
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return None

    expected_sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, sig):
        return None

    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        telegram_id = int(payload["telegram_id"])
        issued_at = int(payload["issued_at"])
    except (ValueError, KeyError, TypeError):
        return None

    if time.time() - issued_at > SESSION_MAX_AGE:
        return None
    # Web users have negative IDs — they bypass the Telegram allow-list
    if telegram_id > 0 and not is_allowed(telegram_id):
        return None

    return telegram_id


# ---------- password auth ----------

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex() + ":" + h.hex()


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, hash_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return hmac.compare_digest(h, expected)
