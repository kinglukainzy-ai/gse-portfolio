import pytest
from httpx import AsyncClient, ASGITransport

import auth
import db
from main import app


@pytest.fixture
def session_cookie():
    token = auth.create_session_token(111111111)
    return {"gse_session": token}


@pytest.fixture
def setup_user():
    db.upsert_user(111111111, "testuser", "Test")


@pytest.mark.asyncio
async def test_config_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config")
    assert resp.status_code == 200
    assert "bot_username" in resp.json()


@pytest.mark.asyncio
async def test_me_unauthenticated():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(session_cookie, setup_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=session_cookie) as client:
        resp = await client.get("/api/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["telegram_id"] == 111111111


@pytest.mark.asyncio
async def test_create_and_list_transactions(session_cookie, setup_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=session_cookie) as client:
        resp = await client.post("/api/transactions", json={
            "symbol": "MTNGH", "side": "buy", "shares": 100, "price": 2.50
        })
        assert resp.status_code == 200

        resp = await client.get("/api/transactions")
        assert resp.status_code == 200
        txs = resp.json()
        assert len(txs) == 1
        assert txs[0]["symbol"] == "MTNGH"


@pytest.mark.asyncio
async def test_transaction_validation(session_cookie, setup_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=session_cookie) as client:
        resp = await client.post("/api/transactions", json={
            "symbol": "MTN GH!", "side": "buy", "shares": 100, "price": 2.50
        })
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_holdings_empty(session_cookie, setup_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=session_cookie) as client:
        resp = await client.get("/api/holdings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["holdings"] == []


@pytest.mark.asyncio
async def test_logout(session_cookie, setup_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=session_cookie) as client:
        resp = await client.post("/api/logout")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_stocks_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stocks")
    assert resp.status_code == 200
    stocks = resp.json()["stocks"]
    assert len(stocks) == 39
    symbols = [s["symbol"] for s in stocks]
    assert "MTNGH" in symbols
    assert "GCB" in symbols
    assert "ACCESS" in symbols


@pytest.mark.asyncio
async def test_symbol_alias_normalization(session_cookie, setup_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=session_cookie) as client:
        resp = await client.post("/api/transactions", json={
            "symbol": "MTN", "side": "buy", "shares": 50, "price": 2.00
        })
        assert resp.status_code == 200
        txs = (await client.get("/api/transactions")).json()
        assert any(t["symbol"] == "MTNGH" for t in txs)


@pytest.mark.asyncio
async def test_delete_transaction(session_cookie, setup_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies=session_cookie) as client:
        resp = await client.post("/api/transactions", json={
            "symbol": "GCB", "side": "buy", "shares": 10, "price": 5.00
        })
        assert resp.status_code == 200
        txs = (await client.get("/api/transactions")).json()
        tx_id = txs[0]["id"]

        del_resp = await client.delete(f"/api/transactions/{tx_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["ok"] is True

        after_txs = (await client.get("/api/transactions")).json()
        assert len(after_txs) == 0
