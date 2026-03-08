"""
rePRICE CLI — FastAPI server for Hyperliquid agent-based trading.

Flow for new users:
  1. POST /agent/create         → generate agent EOA
  2. POST /agent/approve        → main wallet approves agent on HL L1
  3. POST /builder/approve      → main wallet approves builder fee
  4. POST /margin/unified       → enable unified margin (optional)
  5. POST /connect              → establish connection (returning users start here)

Trading:
  POST /order/limit             → place limit order
  POST /order/trigger           → place TP/SL trigger order
  POST /order/cancel            → cancel an order
  POST /leverage                → update leverage

Info:
  GET  /balance/{address}       → clearinghouse state (balance, positions, margin)
  GET  /positions/{address}     → open positions
  GET  /orders/{address}        → open orders
  GET  /fills/{address}         → recent fills
  GET  /agents/{address}        → approved agents
  GET  /prices                  → all mid prices
  GET  /meta                    → exchange metadata (all assets)
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import hl_client

app = FastAPI(
    title="rePRICE CLI",
    description="Hyperliquid agent-based trading API",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# In-memory session store (maps user_address → agent credentials)
# In production you'd persist this or use env vars.
# ---------------------------------------------------------------------------

sessions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateAgentRequest(BaseModel):
    """No params needed — generates a fresh random agent wallet."""
    pass


class ApproveAgentRequest(BaseModel):
    main_private_key: str = Field(..., description="Main wallet private key (hex)")
    agent_address: str = Field(..., description="Agent EOA address to approve")
    agent_name: str = Field(default="rePRICE-CLI", description="Agent name on HL L1")


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
    user_address: str = Field(..., description="Main wallet address")
    asset: str = Field(..., description="Asset symbol (e.g. BTC, ETH)")
    is_buy: bool = Field(..., description="True = buy/long, False = sell/short")
    price: float = Field(..., description="Limit price")
    size: float = Field(..., description="Order size in base asset")
    reduce_only: bool = Field(default=False)
    tif: str = Field(default="Gtc", description="Gtc | Ioc | Alo")
    leverage: Optional[int] = Field(default=None, description="Set leverage before order (optional)")
    is_cross: bool = Field(default=True, description="Cross margin (True) or isolated (False)")


class TriggerOrderRequest(BaseModel):
    user_address: str = Field(..., description="Main wallet address")
    asset: str = Field(..., description="Asset symbol")
    is_buy: bool = Field(..., description="True = buy/long trigger, False = sell/short trigger")
    trigger_price: float = Field(..., description="Trigger price")
    size: float = Field(..., description="Size")
    tpsl: str = Field(default="tp", description="'tp' for take-profit, 'sl' for stop-loss")


class CancelOrderRequest(BaseModel):
    user_address: str = Field(..., description="Main wallet address")
    asset: str = Field(..., description="Asset symbol")
    oid: int = Field(..., description="Order ID to cancel")


class LeverageRequest(BaseModel):
    user_address: str = Field(..., description="Main wallet address")
    asset: str = Field(..., description="Asset symbol")
    leverage: int = Field(..., description="Leverage multiplier (e.g. 10)")
    is_cross: bool = Field(default=True, description="Cross margin (True) or isolated (False)")


# ---------------------------------------------------------------------------
# Helper: get agent creds from session
# ---------------------------------------------------------------------------


def _get_session(user_address: str) -> dict:
    addr = user_address.lower()
    if addr not in sessions:
        raise HTTPException(
            status_code=400,
            detail="No active session. POST /connect first with your agent key.",
        )
    return sessions[addr]


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
    """Approve rePRICE builder fee (main wallet signature)."""
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
    """Establish a trading session: link agent key to main wallet.

    Returning users who already have an approved agent on HL L1
    can skip /agent/create and /agent/approve — just connect.
    """
    # Verify the key is valid
    try:
        derived_address = hl_client.address_from_key(req.agent_private_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid agent key: {e}")

    sessions[req.user_address.lower()] = {
        "user_address": req.user_address,
        "agent_private_key": req.agent_private_key,
        "agent_address": derived_address,
    }

    return {
        "status": "connected",
        "user_address": req.user_address,
        "agent_address": derived_address,
    }


# ============================================================================
# TRADING ENDPOINTS
# ============================================================================


@app.post("/order/limit", tags=["Trading"])
def place_limit_order(req: LimitOrderRequest):
    """Place a limit order via the agent wallet."""
    session = _get_session(req.user_address)

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
def place_trigger_order(req: TriggerOrderRequest):
    """Place a TP/SL trigger order (reduce-only, market execution)."""
    session = _get_session(req.user_address)

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
def cancel_order(req: CancelOrderRequest):
    """Cancel an open order by ID."""
    session = _get_session(req.user_address)

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
def set_leverage(req: LeverageRequest):
    """Update leverage for an asset."""
    session = _get_session(req.user_address)

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
# INFO ENDPOINTS
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
    return {"status": "ok", "sessions": len(sessions)}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
