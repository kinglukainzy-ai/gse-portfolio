import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import auth
import db
import portfolio

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gse-portfolio")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
COOKIE_NAME = "gse_session"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")


@asynccontextmanager
async def lifespan(app):
    auth.assert_secret_key_is_safe()
    db.init_db()
    log.info("GH₵ Portfolio backend started. Allow-listed IDs: %s", auth.ALLOWED_IDS)
    yield


app = FastAPI(title="GH₵ Portfolio", lifespan=lifespan)


# ---------- auth dependency ----------

def require_user(request: Request) -> int:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="not logged in")
    telegram_id = auth.verify_session_token(token)
    if telegram_id is None:
        raise HTTPException(status_code=401, detail="invalid or expired session")
    return telegram_id


# ---------- static / index ----------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/api/config")
def get_config():
    """Public: just enough for the frontend to render the Telegram login widget."""
    return {"bot_username": BOT_USERNAME}


# ---------- auth ----------

@app.post("/api/auth/telegram")
def telegram_login(payload: dict, response: Response):
    if not auth.verify_telegram_login(payload):
        raise HTTPException(status_code=401, detail="invalid Telegram login payload")

    telegram_id = int(payload["id"])
    if not auth.is_allowed(telegram_id):
        raise HTTPException(status_code=403, detail="this account is not on the allow-list")

    db.upsert_user(telegram_id, payload.get("username"), payload.get("first_name"))
    token = auth.create_session_token(telegram_id)
    response.set_cookie(
        COOKIE_NAME, token,
        httponly=True, samesite="lax", secure=COOKIE_SECURE,
        max_age=auth.SESSION_MAX_AGE,
    )
    return {"ok": True, "telegram_id": telegram_id}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(telegram_id: int = Depends(require_user)):
    user = db.get_user(telegram_id)
    return {"telegram_id": telegram_id, "username": user.get("username") if user else None}


# ---------- transactions ----------

class TransactionIn(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=12)
    side: str = Field(..., pattern="^(buy|sell)$")
    shares: float = Field(..., gt=0)
    price: float = Field(..., ge=0)
    trade_date: str | None = Field(None, description="YYYY-MM-DD; defaults to today")


@app.get("/api/transactions")
def list_transactions(telegram_id: int = Depends(require_user)):
    return db.get_transactions(telegram_id)


@app.post("/api/transactions")
def create_transaction(tx: TransactionIn, telegram_id: int = Depends(require_user)):
    symbol = tx.symbol.strip().upper()
    if not symbol.isalnum():
        raise HTTPException(status_code=400, detail="symbol must be alphanumeric")
    try:
        db.add_transaction(telegram_id, symbol, tx.side, tx.shares, tx.price, tx.trade_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.delete("/api/transactions/{tx_id}")
def remove_transaction(tx_id: int, telegram_id: int = Depends(require_user)):
    ok = db.delete_transaction(telegram_id, tx_id)
    if not ok:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"ok": True}


# ---------- holdings / history ----------

@app.get("/api/holdings")
async def holdings(telegram_id: int = Depends(require_user)):
    return await portfolio.get_holdings(telegram_id)


@app.get("/api/stock/{symbol}")
async def stock_detail(symbol: str, telegram_id: int = Depends(require_user)):
    symbol = symbol.strip().upper()
    if not symbol.isalnum():
        raise HTTPException(status_code=400, detail="symbol must be alphanumeric")
    try:
        detail = await portfolio.fetch_stock_detail(symbol)
    except portfolio.PriceFetchError:
        raise HTTPException(status_code=502, detail="could not reach GSE equities API")
    if detail is None:
        raise HTTPException(status_code=404, detail=f"symbol {symbol} not found")
    return detail


@app.get("/api/history")
async def history(symbol: str | None = None, telegram_id: int = Depends(require_user)):
    if symbol:
        symbol = symbol.strip().upper()
        if not symbol.isalnum():
            raise HTTPException(status_code=400, detail="symbol must be alphanumeric")
    return await portfolio.get_history(telegram_id, symbol)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
