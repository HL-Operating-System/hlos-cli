#!/usr/bin/env python3
"""
HLOS CLI — Interactive terminal for Hyperliquid agent-based trading.

Talks to the hlos-cli FastAPI server (local or deployed).
"""
from __future__ import annotations

import os
import sys
import json
import warnings
warnings.filterwarnings("ignore", message="urllib3")

import requests
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.theme import Theme
from rich import box

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_BASE = os.environ.get("HLOS_API_URL", "https://api.hlos.app")
API_KEY = os.environ.get("HLOS_API_KEY", "")  # optional server-level key

theme = Theme({
    "hlos": "bold magenta",
    "success": "bold green",
    "error": "bold red",
    "info": "cyan",
    "muted": "dim white",
    "accent": "bold bright_magenta",
    "price_up": "green",
    "price_down": "red",
})

console = Console(theme=theme)

# ---------------------------------------------------------------------------
# ASCII Banner
# ---------------------------------------------------------------------------

BANNER = """[bold magenta]
 ██╗  ██╗██╗      ██████╗ ███████╗
 ██║  ██║██║     ██╔═══██╗██╔════╝
 ███████║██║     ██║   ██║███████╗
 ██╔══██║██║     ██║   ██║╚════██║
 ██║  ██║███████╗╚██████╔╝███████║
 ╚═╝  ╚═╝╚══════╝ ╚═════╝ ╚══════╝[/bold magenta]"""


def show_banner():
    console.print(BANNER)
    console.print(
        "  [muted]The Hyperliquid Operating System CLI.[/muted]"
    )
    console.print(
        "  [muted]Type[/muted] [accent]help[/accent] [muted]for commands or[/muted] "
        "[accent]quit[/accent] [muted]to exit.[/muted]\n"
    )


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

session = {
    "user_address": None,
    "agent_private_key": None,
    "agent_address": None,
    "session_token": None,
    "connected": False,
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def _headers(auth: bool = False) -> dict:
    """Build request headers. Includes session token for trading endpoints."""
    h = {}
    if API_KEY:
        h["x-api-key"] = API_KEY
    if auth and session.get("session_token"):
        h["Authorization"] = f"Bearer {session['session_token']}"
    return h


def api_get(path: str) -> dict | list | None:
    try:
        r = requests.get(f"{API_BASE}{path}", headers=_headers(), timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        console.print(f"[error]Cannot reach API at {API_BASE}[/error]")
        return None
    except Exception as e:
        console.print(f"[error]API error: {e}[/error]")
        return None


def api_post(path: str, data: dict, auth: bool = False) -> dict | None:
    try:
        r = requests.post(
            f"{API_BASE}{path}",
            json=data,
            headers=_headers(auth=auth),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        console.print(f"[error]Cannot reach API at {API_BASE}[/error]")
        return None
    except requests.exceptions.HTTPError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = str(e)
        console.print(f"[error]{detail}[/error]")
        return None
    except Exception as e:
        console.print(f"[error]API error: {e}[/error]")
        return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_help():
    table = Table(
        title="[accent]Commands[/accent]",
        box=box.ROUNDED,
        border_style="magenta",
        title_style="bold magenta",
    )
    table.add_column("Command", style="accent", min_width=18)
    table.add_column("Description", style="muted")

    cmds = [
        ("create-agent", "Generate a new agent wallet (EOA)"),
        ("approve-agent", "Approve agent on Hyperliquid L1"),
        ("approve-builder", "Approve builder fee (main wallet)"),
        ("unified-margin", "Enable/disable unified margin"),
        ("connect", "Establish trading session"),
        ("disconnect", "End trading session"),
        ("", ""),
        ("buy", "Place a buy/long limit order"),
        ("sell", "Place a sell/short limit order"),
        ("tp", "Set take-profit trigger order"),
        ("sl", "Set stop-loss trigger order"),
        ("cancel", "Cancel an open order"),
        ("leverage", "Set leverage for an asset"),
        ("", ""),
        ("balance", "Check balance & margin info"),
        ("positions", "View open positions"),
        ("orders", "View open orders"),
        ("fills", "View recent trade fills"),
        ("prices", "View current prices"),
        ("agents", "View approved agents"),
        ("", ""),
        ("status", "Show current session info"),
        ("help", "Show this help"),
        ("quit", "Exit HLOS CLI"),
    ]
    for cmd, desc in cmds:
        if not cmd:
            table.add_row("", "")
        else:
            table.add_row(cmd, desc)
    console.print(table)


def cmd_status():
    if session["connected"]:
        console.print(f"[success]Connected[/success]")
        console.print(f"  [muted]User:[/muted]    {session['user_address']}")
        console.print(f"  [muted]Agent:[/muted]   {session['agent_address']}")
        console.print(f"  [muted]API:[/muted]     {API_BASE}")
        console.print(f"  [muted]Session:[/muted] {session['session_token'][:12]}...")
    else:
        console.print("[muted]Not connected. Use[/muted] [accent]connect[/accent] [muted]or[/muted] [accent]create-agent[/accent]")


def cmd_create_agent():
    result = api_post("/agent/create", {})
    if not result:
        return
    session["agent_address"] = result["agent_address"]
    session["agent_private_key"] = result["agent_private_key"]
    console.print(f"\n[success]Agent created![/success]")
    console.print(f"  [muted]Address:[/muted]     {result['agent_address']}")
    console.print(f"  [muted]Private Key:[/muted] {result['agent_private_key']}")
    console.print(f"\n  [error]Save the private key! You need it to connect.[/error]\n")


def cmd_approve_agent():
    main_key = Prompt.ask("[accent]Main wallet private key[/accent]")
    agent_addr = Prompt.ask(
        "[accent]Agent address[/accent]",
        default=session.get("agent_address") or "",
    )
    if not main_key or not agent_addr:
        console.print("[error]Both fields required.[/error]")
        return
    result = api_post("/agent/approve", {
        "main_private_key": main_key,
        "agent_address": agent_addr,
    })
    if result:
        console.print(f"[success]Agent approved on Hyperliquid L1.[/success]")


def cmd_approve_builder():
    main_key = Prompt.ask("[accent]Main wallet private key[/accent]")
    if not main_key:
        return
    result = api_post("/builder/approve", {"main_private_key": main_key})
    if result:
        console.print(f"[success]Builder fee approved (0.025%).[/success]")


def cmd_unified_margin():
    main_key = Prompt.ask("[accent]Main wallet private key[/accent]")
    enable = Confirm.ask("[accent]Enable unified margin?[/accent]", default=True)
    result = api_post("/margin/unified", {
        "main_private_key": main_key,
        "enabled": enable,
    })
    if result:
        action = "enabled" if enable else "disabled"
        console.print(f"[success]Unified margin {action}.[/success]")


def cmd_connect():
    user_addr = Prompt.ask(
        "[accent]Main wallet address[/accent]",
        default=session.get("user_address") or "",
    )
    agent_key = Prompt.ask(
        "[accent]Agent private key[/accent]",
        default=session.get("agent_private_key") or "",
    )
    if not user_addr or not agent_key:
        console.print("[error]Both fields required.[/error]")
        return
    result = api_post("/connect", {
        "user_address": user_addr,
        "agent_private_key": agent_key,
    })
    if result:
        session["user_address"] = result["user_address"]
        session["agent_address"] = result["agent_address"]
        session["agent_private_key"] = agent_key
        session["session_token"] = result["session_token"]
        session["connected"] = True
        console.print(f"\n[success]Connected![/success]")
        console.print(f"  [muted]User:[/muted]    {result['user_address']}")
        console.print(f"  [muted]Agent:[/muted]   {result['agent_address']}")
        console.print(f"  [muted]Session:[/muted] {result['session_token'][:12]}...\n")


def cmd_disconnect():
    if not session["connected"]:
        console.print("[muted]Not connected.[/muted]")
        return
    api_post("/disconnect", {}, auth=True)
    session["session_token"] = None
    session["connected"] = False
    console.print("[success]Disconnected. Session cleared.[/success]")


def _require_connected() -> bool:
    if not session["connected"]:
        console.print("[error]Not connected. Use[/error] [accent]connect[/accent] [error]first.[/error]")
        return False
    return True


def cmd_order(is_buy: bool):
    if not _require_connected():
        return
    side = "BUY" if is_buy else "SELL"
    console.print(f"\n[accent]Place {side} order[/accent]")
    asset = Prompt.ask("  [muted]Asset[/muted]", default="BTC").upper()
    price = Prompt.ask("  [muted]Price[/muted]")
    size = Prompt.ask("  [muted]Size[/muted]")
    lev = Prompt.ask("  [muted]Leverage (or skip)[/muted]", default="")
    tif = Prompt.ask("  [muted]TIF[/muted]", default="Gtc", choices=["Gtc", "Ioc", "Alo"])

    body = {
        "asset": asset,
        "is_buy": is_buy,
        "price": float(price),
        "size": float(size),
        "tif": tif,
    }
    if lev:
        body["leverage"] = int(lev)

    result = api_post("/order/limit", body, auth=True)
    if result:
        console.print(f"[success]Order placed![/success]")
        console.print(f"  [muted]{json.dumps(result.get('response', {}), indent=2)}[/muted]")


def cmd_trigger(tpsl: str):
    if not _require_connected():
        return
    label = "Take Profit" if tpsl == "tp" else "Stop Loss"
    console.print(f"\n[accent]Set {label}[/accent]")
    asset = Prompt.ask("  [muted]Asset[/muted]", default="BTC").upper()
    trigger_price = Prompt.ask("  [muted]Trigger price[/muted]")
    size = Prompt.ask("  [muted]Size[/muted]")
    # For TP on a long, the trigger sells (is_buy=False). For SL on a long, also sells.
    is_buy = Confirm.ask("  [muted]Buy side trigger?[/muted]", default=False)

    result = api_post("/order/trigger", {
        "asset": asset,
        "is_buy": is_buy,
        "trigger_price": float(trigger_price),
        "size": float(size),
        "tpsl": tpsl,
    }, auth=True)
    if result:
        console.print(f"[success]{label} set![/success]")


def cmd_cancel():
    if not _require_connected():
        return
    asset = Prompt.ask("[accent]Asset[/accent]", default="BTC").upper()
    oid = Prompt.ask("[accent]Order ID[/accent]")
    result = api_post("/order/cancel", {
        "asset": asset,
        "oid": int(oid),
    }, auth=True)
    if result:
        console.print(f"[success]Order cancelled.[/success]")


def cmd_leverage():
    if not _require_connected():
        return
    asset = Prompt.ask("[accent]Asset[/accent]", default="BTC").upper()
    lev = Prompt.ask("[accent]Leverage[/accent]")
    is_cross = Confirm.ask("[accent]Cross margin?[/accent]", default=True)
    result = api_post("/leverage", {
        "asset": asset,
        "leverage": int(lev),
        "is_cross": is_cross,
    }, auth=True)
    if result:
        console.print(f"[success]{asset} leverage set to {lev}x.[/success]")


def cmd_balance():
    addr = session.get("user_address") or Prompt.ask("[accent]Wallet address[/accent]")
    if not addr:
        return
    data = api_get(f"/balance/{addr}")
    if not data:
        return

    perps = data.get("perps", {})
    margin = perps.get("marginSummary", {})

    table = Table(
        title="[accent]Account Balance[/accent]",
        box=box.ROUNDED,
        border_style="magenta",
    )
    table.add_column("Metric", style="muted")
    table.add_column("Value", style="info", justify="right")

    table.add_row("Account Value", f"${float(margin.get('accountValue', 0)):,.2f}")
    table.add_row("Total Margin Used", f"${float(margin.get('totalMarginUsed', 0)):,.2f}")
    table.add_row("Total Position Value", f"${float(margin.get('totalNtlPos', 0)):,.2f}")
    table.add_row("Withdrawable", f"${float(margin.get('withdrawable', 0)):,.2f}")
    console.print(table)


def cmd_positions():
    addr = session.get("user_address") or Prompt.ask("[accent]Wallet address[/accent]")
    if not addr:
        return
    data = api_get(f"/positions/{addr}")
    if not data:
        return

    positions = data.get("positions", [])
    if not positions:
        console.print("[muted]No open positions.[/muted]")
        return

    table = Table(
        title=f"[accent]Open Positions ({data['count']})[/accent]",
        box=box.ROUNDED,
        border_style="magenta",
    )
    table.add_column("Asset", style="accent")
    table.add_column("Side", min_width=5)
    table.add_column("Size", justify="right", style="info")
    table.add_column("Entry", justify="right", style="muted")
    table.add_column("Mark", justify="right", style="muted")
    table.add_column("uPnL", justify="right")
    table.add_column("Leverage", justify="right", style="muted")

    for p in positions:
        pos = p.get("position", {})
        szi = float(pos.get("szi", "0"))
        entry = float(pos.get("entryPx", "0"))
        upnl = float(pos.get("unrealizedPnl", "0"))
        lev = pos.get("leverage", {})
        lev_val = lev.get("value", "?")
        lev_type = lev.get("type", "")

        side_text = Text("LONG" if szi > 0 else "SHORT")
        side_text.stylize("price_up" if szi > 0 else "price_down")

        pnl_text = Text(f"${upnl:+,.2f}")
        pnl_text.stylize("price_up" if upnl >= 0 else "price_down")

        table.add_row(
            pos.get("coin", "?"),
            side_text,
            f"{abs(szi):.4f}",
            f"${entry:,.2f}",
            f"${float(pos.get('positionValue', 0)) / abs(szi) if szi else 0:,.2f}",
            pnl_text,
            f"{lev_val}x {lev_type}",
        )

    console.print(table)


def cmd_orders():
    addr = session.get("user_address") or Prompt.ask("[accent]Wallet address[/accent]")
    if not addr:
        return
    data = api_get(f"/orders/{addr}")
    if not data:
        return

    orders = data.get("orders", [])
    if not orders:
        console.print("[muted]No open orders.[/muted]")
        return

    table = Table(
        title=f"[accent]Open Orders ({data['count']})[/accent]",
        box=box.ROUNDED,
        border_style="magenta",
    )
    table.add_column("OID", style="muted")
    table.add_column("Asset", style="accent")
    table.add_column("Side")
    table.add_column("Price", justify="right", style="info")
    table.add_column("Size", justify="right", style="info")
    table.add_column("Type", style="muted")

    for o in orders:
        side_text = Text("BUY" if o.get("side") == "B" else "SELL")
        side_text.stylize("price_up" if o.get("side") == "B" else "price_down")
        table.add_row(
            str(o.get("oid", "?")),
            o.get("coin", "?"),
            side_text,
            f"${float(o.get('limitPx', '0')):,.2f}",
            o.get("sz", "?"),
            o.get("orderType", "?"),
        )

    console.print(table)


def cmd_fills():
    addr = session.get("user_address") or Prompt.ask("[accent]Wallet address[/accent]")
    if not addr:
        return
    data = api_get(f"/fills/{addr}")
    if not data:
        return

    fills = data.get("fills", [])
    if not fills:
        console.print("[muted]No recent fills.[/muted]")
        return

    table = Table(
        title=f"[accent]Recent Fills ({min(len(fills), 20)} shown)[/accent]",
        box=box.ROUNDED,
        border_style="magenta",
    )
    table.add_column("Asset", style="accent")
    table.add_column("Side")
    table.add_column("Price", justify="right", style="info")
    table.add_column("Size", justify="right", style="info")
    table.add_column("Fee", justify="right", style="muted")

    for f in fills[:20]:
        side_text = Text("BUY" if f.get("side") == "B" else "SELL")
        side_text.stylize("price_up" if f.get("side") == "B" else "price_down")
        table.add_row(
            f.get("coin", "?"),
            side_text,
            f"${float(f.get('px', '0')):,.2f}",
            f.get("sz", "?"),
            f"${float(f.get('fee', '0')):.4f}",
        )

    console.print(table)


def cmd_prices():
    data = api_get("/prices")
    if not data:
        return

    # Show top perp assets (no @ prefix = named perps)
    named = {k: v for k, v in data.items() if not k.startswith("@") and "/" not in k}
    sorted_assets = sorted(named.items())

    table = Table(
        title=f"[accent]Prices ({len(sorted_assets)} perp assets)[/accent]",
        box=box.ROUNDED,
        border_style="magenta",
    )
    table.add_column("Asset", style="accent", min_width=8)
    table.add_column("Mid Price", justify="right", style="info")

    for asset, price in sorted_assets:
        px = float(price)
        if px >= 1:
            table.add_row(asset, f"${px:,.2f}")
        else:
            table.add_row(asset, f"${px:.6f}")

    console.print(table)


def cmd_agents():
    addr = session.get("user_address") or Prompt.ask("[accent]Wallet address[/accent]")
    if not addr:
        return
    data = api_get(f"/agents/{addr}")
    if not data:
        return

    agents = data.get("agents", [])
    if not agents:
        console.print("[muted]No approved agents.[/muted]")
        return

    table = Table(
        title="[accent]Approved Agents[/accent]",
        box=box.ROUNDED,
        border_style="magenta",
    )
    table.add_column("Address", style="info")
    table.add_column("Name", style="muted")

    for a in agents:
        table.add_row(a.get("address", "?"), a.get("name", "?"))

    console.print(table)


# ---------------------------------------------------------------------------
# Command router
# ---------------------------------------------------------------------------

COMMANDS = {
    "help": cmd_help,
    "status": cmd_status,
    "create-agent": cmd_create_agent,
    "approve-agent": cmd_approve_agent,
    "approve-builder": cmd_approve_builder,
    "unified-margin": cmd_unified_margin,
    "connect": cmd_connect,
    "disconnect": cmd_disconnect,
    "buy": lambda: cmd_order(True),
    "sell": lambda: cmd_order(False),
    "tp": lambda: cmd_trigger("tp"),
    "sl": lambda: cmd_trigger("sl"),
    "cancel": cmd_cancel,
    "leverage": cmd_leverage,
    "balance": cmd_balance,
    "positions": cmd_positions,
    "orders": cmd_orders,
    "fills": cmd_fills,
    "prices": cmd_prices,
    "agents": cmd_agents,
}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main():
    show_banner()

    # Health check
    health = api_get("/health")
    if health:
        key_status = " [muted](API key required)[/muted]" if health.get("api_key_required") else ""
        console.print(f"  [success]API online[/success] [muted]({API_BASE})[/muted]{key_status}\n")
    else:
        console.print(f"  [error]API offline[/error] [muted]({API_BASE})[/muted]\n")

    while True:
        try:
            raw = Prompt.ask("[bold magenta]>>[/bold magenta]").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[muted]Goodbye.[/muted]")
            break

        if not raw:
            continue
        if raw in ("quit", "exit", "q"):
            console.print("[muted]Goodbye.[/muted]")
            break

        handler = COMMANDS.get(raw)
        if handler:
            try:
                handler()
            except KeyboardInterrupt:
                console.print("\n[muted]Cancelled.[/muted]")
            except Exception as e:
                console.print(f"[error]Error: {e}[/error]")
        else:
            console.print(f"[error]Unknown command:[/error] {raw}. Type [accent]help[/accent] for commands.")

        console.print()


if __name__ == "__main__":
    main()
