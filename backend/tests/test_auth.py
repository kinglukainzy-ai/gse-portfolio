import time
import auth


def test_session_roundtrip():
    token = auth.create_session_token(111111111)
    assert auth.verify_session_token(token) == 111111111


def test_session_expired(monkeypatch):
    token = auth.create_session_token(111111111)
    future = time.time() + auth.SESSION_MAX_AGE + 100
    monkeypatch.setattr(time, "time", lambda: future)
    assert auth.verify_session_token(token) is None


def test_session_tampered():
    token = auth.create_session_token(111111111)
    parts = token.split(".")
    tampered = parts[0] + ".0000000000000000000000000000000000000000000000000000000000000000"
    assert auth.verify_session_token(tampered) is None


def test_session_not_allowed(monkeypatch):
    token = auth.create_session_token(999999999)
    assert auth.verify_session_token(token) is None


def test_session_garbage():
    assert auth.verify_session_token("") is None
    assert auth.verify_session_token("not.a.token") is None
    assert auth.verify_session_token("garbage") is None


def test_is_allowed():
    assert auth.is_allowed(111111111) is True
    assert auth.is_allowed(999999999) is False


def test_assert_secret_key_safe(monkeypatch):
    import pytest
    monkeypatch.setattr(auth, "SECRET_KEY", "a" * 64)
    auth.assert_secret_key_is_safe()

    monkeypatch.setattr(auth, "SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        auth.assert_secret_key_is_safe()

    monkeypatch.setattr(auth, "SECRET_KEY", "short")
    with pytest.raises(RuntimeError):
        auth.assert_secret_key_is_safe()

    monkeypatch.setattr(auth, "SECRET_KEY", "change-me-in-production")
    with pytest.raises(RuntimeError):
        auth.assert_secret_key_is_safe()
