"""
HLOS CLI — FastAPI server for Hyperliquid agent-based trading.

Security:
  - Optional server-level API key via HLOS_API_KEY env var
  - Session tokens: /connect returns a secret token; all trading
    endpoints require it via Authorization header
  - Private keys are never logged or returned in responses (except
    /agent/create which generates a new key for the user to save)
  - Info endpoints (GET) are public — no auth required

Flow for new users:
  1. POST /agent/create         → generate agent EOA
  2. POST /agent/approve        → main wallet approves agent on HL L1
  3. POST /builder/approve      → main wallet approves builder fee
  4. POST /margin/unified       → enable unified margin (optional)
  5. POST /connect              → establish connection → returns session_token
  6. Use session_token in Authorization header for all trading endpoints

Trading:
  POST /order/limit             → place limit order
  POST /order/trigger           → place TP/SL trigger order
  POST /order/cancel            → cancel an order
  POST /leverage                → update leverage

Info (public, no auth):
  GET  /balance/{address}       → clearinghouse state
  GET  /positions/{address}     → open positions
  GET  /orders/{address}        → open orders
  GET  /fills/{address}         → recent fills
  GET  /agents/{address}        → approved agents
  GET  /prices                  → all mid prices
  GET  /meta                    → exchange metadata
"""

from __future__ import annotations

import os
import secrets
import logging

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Optional
import hl_client

# ---------------------------------------------------------------------------
# Logging — suppress request body logging to protect private keys
# ---------------------------------------------------------------------------

logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

app = FastAPI(
    title="HLOS CLI",
    description="Hyperliquid agent-based trading API",
    version="0.2.0",
)

# ---------------------------------------------------------------------------
# Server-level API key (optional — set HLOS_API_KEY env var to enable)
# When set, ALL non-GET requests require this key in x-api-key header.
# Info endpoints (GET) remain public.
# ---------------------------------------------------------------------------

SERVER_API_KEY = os.environ.get("HLOS_API_KEY")

# ---------------------------------------------------------------------------
# Session store: session_token → session data
# Sessions are keyed by a random token, NOT by user_address.
# This prevents anyone from trading on your session just by knowing
# your wallet address.
# ---------------------------------------------------------------------------

sessions: dict[str, dict] = {}  # token → {user_address, agent_private_key, agent_address}
address_to_token: dict[str, str] = {}  # user_address → token (for lookup/revocation)

# Security scheme for Swagger docs
bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def check_api_key(request: Request, call_next):
    """If HLOS_API_KEY is set, require it for all POST requests."""
    if SERVER_API_KEY and request.method == "POST":
        provided = request.headers.get("x-api-key", "")
        if provided != SERVER_API_KEY:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing x-api-key header."},
            )
    return await call_next(request)


def _get_session_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """Extract and validate session from Bearer token."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header. Use: Authorization: Bearer <session_token>",
        )
    token = credentials.credentials
    if token not in sessions:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session token. POST /connect to get a new one.",
        )
    return sessions[token]


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateAgentRequest(BaseModel):
    """No params needed — generates a fresh random agent wallet."""
    pass


class ApproveAgentRequest(BaseModel):
    main_private_key: str = Field(..., description="Main wallet private key (hex)")
    agent_address: str = Field(..., description="Agent EOA address to approve")
    agent_name: str = Field(default="HLOS", description="Agent name on HL L1")


class ApproveBuilderRequest(BaseModel):
    main_private_key: str = Field(..., description="Main wallet private key (hex)")


class UnifiedMarginRequest(BaseModel):
    main_private_key: str = Field(..., description="Main wallet private key (hex)")
    enabled: bool = Field(default=True, description="True to enable, False to disable")


class ConnectRequest(BaseModel):
    """Establish a session: link agent key to main wallet for trading."""
    user_address: str = Field(..., description="Main wallet address")
    agent_private_key: str = Field(..., description="Agent wallet private key (hex)")


class LimitOrderRequest(BaseModel):
    asset: str = Field(..., description="Asset symbol (e.g. BTC, ETH)")
    is_buy: bool = Field(..., description="True = buy/long, False = sell/short")
    price: float = Field(..., description="Limit price")
    size: float = Field(..., description="Order size in base asset")
    reduce_only: bool = Field(default=False)
    tif: str = Field(default="Gtc", description="Gtc | Ioc | Alo")
    leverage: Optional[int] = Field(default=None, description="Set leverage before order (optional)")
    is_cross: bool = Field(default=True, description="Cross margin (True) or isolated (False)")


class TriggerOrderRequest(BaseModel):
    asset: str = Field(..., description="Asset symbol")
    is_buy: bool = Field(..., description="True = buy/long trigger, False = sell/short trigger")
    trigger_price: float = Field(..., description="Trigger price")
    size: float = Field(..., description="Size")
    tpsl: str = Field(default="tp", description="'tp' for take-profit, 'sl' for stop-loss")


class CancelOrderRequest(BaseModel):
    asset: str = Field(..., description="Asset symbol")
    oid: int = Field(..., description="Order ID to cancel")


class LeverageRequest(BaseModel):
    asset: str = Field(..., description="Asset symbol")
    leverage: int = Field(..., description="Leverage multiplier (e.g. 10)")
    is_cross: bool = Field(default=True, description="Cross margin (True) or isolated (False)")


# ============================================================================
# SETUP ENDPOINTS
# ============================================================================


@app.post("/agent/create", tags=["Setup"])
def create_agent():
    """Generate a new random agent wallet (EOA). Save the private key!"""
    agent = hl_client.generate_agent_key()
    return {
        "agent_address": agent["address"],
        "agent_private_key": agent["private_key"],
        "message": "Save this private key securely. You need it to connect.",
    }


@app.post("/agent/approve", tags=["Setup"])
def approve_agent(req: ApproveAgentRequest):
    """Approve an agent address on Hyperliquid L1 (main wallet signature)."""
    try:
        result = hl_client.approve_agent(
            req.main_private_key, req.agent_address, req.agent_name
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/builder/approve", tags=["Setup"])
def approve_builder(req: ApproveBuilderRequest):
    """Approve HLOS builder fee (main wallet signature)."""
    try:
        result = hl_client.approve_builder_fee(req.main_private_key)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/margin/unified", tags=["Setup"])
def unified_margin(req: UnifiedMarginRequest):
    """Enable or disable unified account margin (main wallet signature)."""
    try:
        result = hl_client.set_unified_margin(req.main_private_key, req.enabled)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/connect", tags=["Setup"])
def connect(req: ConnectRequest):
    """Establish a trading session. Returns a session_token.

    Use the session_token as a Bearer token in the Authorization header
    for all trading endpoints. This replaces user_address in request bodies.

    Returning users who already have an approved agent on HL L1
    can skip /agent/create and /agent/approve — just connect.
    """
    # Verify the key is valid
    try:
        derived_address = hl_client.address_from_key(req.agent_private_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid agent key: {e}")

    # Revoke any existing session for this address
    addr_lower = req.user_address.lower()
    old_token = address_to_token.get(addr_lower)
    if old_token and old_token in sessions:
        del sessions[old_token]

    # Generate a new session token
    token = secrets.token_urlsafe(32)

    sessions[token] = {
        "user_address": req.user_address,
        "agent_private_key": req.agent_private_key,
        "agent_address": derived_address,
    }
    address_to_token[addr_lower] = token

    return {
        "status": "connected",
        "user_address": req.user_address,
        "agent_address": derived_address,
        "session_token": token,
        "message": "Use this token as: Authorization: Bearer <session_token>",
    }


@app.post("/disconnect", tags=["Setup"])
def disconnect(session: dict = Depends(_get_session_from_token)):
    """Revoke the current session. Agent key is cleared from server memory."""
    addr = session["user_address"].lower()
    token = address_to_token.get(addr)
    if token and token in sessions:
        del sessions[token]
    if addr in address_to_token:
        del address_to_token[addr]
    return {"status": "disconnected"}


# ============================================================================
# TRADING ENDPOINTS (require Bearer session_token)
# ============================================================================


@app.post("/order/limit", tags=["Trading"])
def place_limit_order(
    req: LimitOrderRequest,
    session: dict = Depends(_get_session_from_token),
):
    """Place a limit order via the agent wallet. Requires session token."""
    # Optionally set leverage first
    if req.leverage is not None:
        try:
            hl_client.update_leverage(
                session["agent_private_key"],
                session["user_address"],
                req.asset,
                req.leverage,
                req.is_cross,
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to set leverage: {e}",
            )

    try:
        result = hl_client.place_limit_order(
            agent_private_key=session["agent_private_key"],
            user_address=session["user_address"],
            asset=req.asset,
            is_buy=req.is_buy,
            price=req.price,
            size=req.size,
            reduce_only=req.reduce_only,
            tif=req.tif,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/order/trigger", tags=["Trading"])
def place_trigger_order(
    req: TriggerOrderRequest,
    session: dict = Depends(_get_session_from_token),
):
    """Place a TP/SL trigger order (reduce-only, market execution). Requires session token."""
    try:
        result = hl_client.place_trigger_order(
            agent_private_key=session["agent_private_key"],
            user_address=session["user_address"],
            asset=req.asset,
            is_buy=req.is_buy,
            trigger_price=req.trigger_price,
            size=req.size,
            tpsl=req.tpsl,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/order/cancel", tags=["Trading"])
def cancel_order(
    req: CancelOrderRequest,
    session: dict = Depends(_get_session_from_token),
):
    """Cancel an open order by ID. Requires session token."""
    try:
        result = hl_client.cancel_order(
            agent_private_key=session["agent_private_key"],
            user_address=session["user_address"],
            asset=req.asset,
            oid=req.oid,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/leverage", tags=["Trading"])
def set_leverage(
    req: LeverageRequest,
    session: dict = Depends(_get_session_from_token),
):
    """Update leverage for an asset. Requires session token."""
    try:
        result = hl_client.update_leverage(
            agent_private_key=session["agent_private_key"],
            user_address=session["user_address"],
            asset=req.asset,
            leverage=req.leverage,
            is_cross=req.is_cross,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# INFO ENDPOINTS (public — no auth required)
# ============================================================================


@app.get("/balance/{address}", tags=["Info"])
def get_balance(address: str):
    """Clearinghouse state: account value, margin, withdrawable, and positions."""
    try:
        state = hl_client.get_user_state(address)
        spot = hl_client.get_spot_clearinghouse_state(address)
        return {"perps": state, "spot": spot}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/positions/{address}", tags=["Info"])
def get_positions(address: str):
    """Open positions extracted from clearinghouse state."""
    try:
        state = hl_client.get_user_state(address)
        positions = [
            p for p in state.get("assetPositions", [])
            if float(p.get("position", {}).get("szi", "0")) != 0
        ]
        return {"positions": positions, "count": len(positions)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/orders/{address}", tags=["Info"])
def get_orders(address: str):
    """All open orders."""
    try:
        orders = hl_client.get_open_orders(address)
        return {"orders": orders, "count": len(orders)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/fills/{address}", tags=["Info"])
def get_fills(address: str):
    """Recent trade fills."""
    try:
        fills = hl_client.get_user_fills(address)
        return {"fills": fills, "count": len(fills)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/agents/{address}", tags=["Info"])
def get_agents(address: str):
    """Approved agents for a wallet."""
    try:
        agents = hl_client.get_extra_agents(address)
        return {"agents": agents}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/prices", tags=["Info"])
def get_prices():
    """All current mid prices."""
    try:
        return hl_client.get_all_mids()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/meta", tags=["Info"])
def get_meta():
    """Exchange metadata — all listed perpetual assets."""
    try:
        return hl_client.get_meta()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Health
# ============================================================================


@app.get("/health")
def health():
    return {
        "status": "ok",
        "sessions": len(sessions),
        "api_key_required": SERVER_API_KEY is not None,
    }


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
