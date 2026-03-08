"""
Hyperliquid client wrapper.

Handles agent wallet management, signing, and all exchange/info API calls
using the official hyperliquid-python-sdk.
"""

from __future__ import annotations

import secrets
import json
import requests
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUILDER_ADDRESS = "0xeFFC82C750f16929F4D8283E8057007D1bB59092"
BUILDER_FEE = 25  # tenths of a basis point: 2.5 bps = 0.025%
BUILDER_MAX_FEE_RATE = "0.025%"
MAINNET_API = "https://api.hyperliquid.xyz"

# ---------------------------------------------------------------------------
# Wallet / Agent helpers
# ---------------------------------------------------------------------------


def generate_agent_key() -> dict:
    """Generate a fresh random agent wallet (EOA)."""
    acct = Account.create(extra_entropy=secrets.token_hex(32))
    return {
        "address": acct.address,
        "private_key": acct.key.hex(),
    }


def address_from_key(private_key: str) -> str:
    """Derive address from a hex private key."""
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    return Account.from_key(private_key).address


# ---------------------------------------------------------------------------
# SDK wrappers
# ---------------------------------------------------------------------------


def _make_info(base_url: str = MAINNET_API) -> Info:
    return Info(base_url, skip_ws=True)


def _make_exchange(
    private_key: str,
    base_url: str = MAINNET_API,
    account_address: str | None = None,
) -> Exchange:
    """Build an Exchange instance.

    If account_address is set the SDK signs with private_key but sends
    the action on behalf of account_address (agent trading mode).
    """
    wallet = Account.from_key(
        private_key if private_key.startswith("0x") else f"0x{private_key}"
    )
    return Exchange(
        wallet,
        base_url,
        account_address=account_address,
    )


# ---------------------------------------------------------------------------
# Agent approval (main wallet signs to authorize agent on HL L1)
# ---------------------------------------------------------------------------


def approve_agent(
    main_private_key: str,
    agent_address: str,
    agent_name: str = "HLOS",
    base_url: str = MAINNET_API,
) -> dict:
    """Approve an agent address on Hyperliquid L1.

    Must be called with the *main* wallet key. The agent can then trade
    on behalf of the main wallet.
    """
    exchange = _make_exchange(main_private_key, base_url)
    result = exchange.approve_agent(agent_address, agent_name)
    return {"status": "ok", "response": result}


# ---------------------------------------------------------------------------
# Builder fee approval
# ---------------------------------------------------------------------------


def approve_builder_fee(
    main_private_key: str,
    base_url: str = MAINNET_API,
) -> dict:
    """Approve HLOS builder fee (main wallet signature required)."""
    exchange = _make_exchange(main_private_key, base_url)
    result = exchange.approve_builder_fee(BUILDER_ADDRESS, BUILDER_MAX_FEE_RATE)
    return {"status": "ok", "response": result}


# ---------------------------------------------------------------------------
# Unified margin
# ---------------------------------------------------------------------------


def set_unified_margin(
    main_private_key: str,
    enabled: bool = True,
    base_url: str = MAINNET_API,
) -> dict:
    """Enable or disable unified account margin (main wallet signature)."""
    exchange = _make_exchange(main_private_key, base_url)
    # The SDK exposes set_referrer / update_leverage etc but for
    # userSetAbstraction we need a raw exchange action.
    action = {
        "type": "userSetAbstraction",
        "abstraction": "unifiedAccount" if enabled else "disabled",
    }
    # Use the internal post helper to sign & send the action
    timestamp = exchange._timestamp()  # noqa: SLF001
    signature = exchange._sign_l1_action(action, None, timestamp)  # noqa: SLF001
    payload = {
        "action": action,
        "nonce": timestamp,
        "signature": signature,
        "vaultAddress": None,
    }
    resp = requests.post(f"{base_url}/exchange", json=payload, timeout=10)
    return {"status": "ok", "response": resp.json()}


# ---------------------------------------------------------------------------
# Info queries
# ---------------------------------------------------------------------------


def get_user_state(user_address: str, base_url: str = MAINNET_API) -> dict:
    """Clearinghouse state: balances, positions, margin info."""
    info = _make_info(base_url)
    return info.user_state(user_address)


def get_open_orders(user_address: str, base_url: str = MAINNET_API) -> list:
    """All open orders for the user."""
    info = _make_info(base_url)
    return info.open_orders(user_address)


def get_user_fills(user_address: str, base_url: str = MAINNET_API) -> list:
    """Recent fills / trade history."""
    info = _make_info(base_url)
    return info.user_fills(user_address)


def get_all_mids(base_url: str = MAINNET_API) -> dict:
    """All mid prices keyed by asset name."""
    info = _make_info(base_url)
    return info.all_mids()


def get_meta(base_url: str = MAINNET_API) -> dict:
    """Exchange metadata (all listed perp assets)."""
    info = _make_info(base_url)
    return info.meta()


def get_spot_meta(base_url: str = MAINNET_API) -> dict:
    """Spot exchange metadata."""
    resp = requests.post(
        f"{base_url}/info", json={"type": "spotMeta"}, timeout=10
    )
    return resp.json()


def get_extra_agents(user_address: str, base_url: str = MAINNET_API) -> list:
    """Query approved agents for a user."""
    resp = requests.post(
        f"{base_url}/info",
        json={"type": "extraAgents", "user": user_address},
        timeout=10,
    )
    return resp.json()


def get_spot_clearinghouse_state(
    user_address: str, base_url: str = MAINNET_API
) -> dict:
    """Spot balances (USDC, HYPE, etc in HyperCore spot wallet)."""
    resp = requests.post(
        f"{base_url}/info",
        json={"type": "spotClearinghouseState", "user": user_address},
        timeout=10,
    )
    return resp.json()


# ---------------------------------------------------------------------------
# Order placement (agent signs — no wallet popup needed)
# ---------------------------------------------------------------------------


def place_limit_order(
    agent_private_key: str,
    user_address: str,
    asset: str,
    is_buy: bool,
    price: float,
    size: float,
    reduce_only: bool = False,
    tif: str = "Gtc",
    base_url: str = MAINNET_API,
) -> dict:
    """Place a limit order via the agent wallet.

    Args:
        agent_private_key: Agent EOA private key (hex).
        user_address: Main wallet address the agent trades on behalf of.
        asset: Asset symbol (e.g. "BTC", "ETH").
        is_buy: True for buy/long, False for sell/short.
        price: Limit price.
        size: Order size in base asset.
        reduce_only: If True, only reduces existing position.
        tif: Time-in-force — "Gtc", "Ioc", or "Alo".
    """
    exchange = _make_exchange(agent_private_key, base_url, account_address=user_address)

    order_type = {"limit": {"tif": tif}}
    result = exchange.order(
        asset,
        is_buy,
        size,
        price,
        order_type,
        reduce_only=reduce_only,
        builder={
            "b": BUILDER_ADDRESS,
            "f": BUILDER_FEE,
        },
    )
    return {"status": "ok", "response": result}


def place_trigger_order(
    agent_private_key: str,
    user_address: str,
    asset: str,
    is_buy: bool,
    trigger_price: float,
    size: float,
    tpsl: str = "tp",
    base_url: str = MAINNET_API,
) -> dict:
    """Place a TP or SL trigger order (reduce-only, market execution).

    Args:
        tpsl: "tp" for take-profit, "sl" for stop-loss.
    """
    exchange = _make_exchange(agent_private_key, base_url, account_address=user_address)

    order_type = {
        "trigger": {
            "isMarket": True,
            "triggerPx": trigger_price,
            "tpsl": tpsl,
        }
    }
    result = exchange.order(
        asset,
        is_buy,
        size,
        trigger_price,
        order_type,
        reduce_only=True,
        builder={
            "b": BUILDER_ADDRESS,
            "f": BUILDER_FEE,
        },
    )
    return {"status": "ok", "response": result}


# ---------------------------------------------------------------------------
# Cancel orders
# ---------------------------------------------------------------------------


def cancel_order(
    agent_private_key: str,
    user_address: str,
    asset: str,
    oid: int,
    base_url: str = MAINNET_API,
) -> dict:
    """Cancel an open order by order ID."""
    exchange = _make_exchange(agent_private_key, base_url, account_address=user_address)
    result = exchange.cancel(asset, oid)
    return {"status": "ok", "response": result}


# ---------------------------------------------------------------------------
# Leverage
# ---------------------------------------------------------------------------


def update_leverage(
    agent_private_key: str,
    user_address: str,
    asset: str,
    leverage: int,
    is_cross: bool = True,
    base_url: str = MAINNET_API,
) -> dict:
    """Update leverage for an asset. is_cross=True for cross margin."""
    exchange = _make_exchange(agent_private_key, base_url, account_address=user_address)
    result = exchange.update_leverage(leverage, asset, is_cross=is_cross)
    return {"status": "ok", "response": result}
