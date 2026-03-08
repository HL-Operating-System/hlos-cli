# HLOS-CLI

A CLI for agents and quants to automate their way around the Hyperliquid Operating System.

## Install

```bash
git clone
cd hlos-cli
pip install -r requirements.txt
python3 cli.py
```

## How It Works

HLOS uses an **Agent Wallet (EOA)**-- your main wallet approves this EOA (the "agent") that can trade on its behalf without requiring your main key for every order(true one-click trading). Keys are never stored permanently, they only live in server memory during an active session and get wiped on /disconnect which is identical to the Hyperliquid Exchange on the L1.

**New users** go through a one-time setup, then trade via the agent. **Returning users** skip straight to `/connect`.

---

## New User Agent Setup: (Commands In Terminal)

### 1. Generate an agent wallet

```bash
create-agent
```

### 2. Approve the agent on Hyperliquid L1

```bash
approve-agent
```

### 3. Approve builder fee

```bash
approve-builder
```

### 4. Enable unified margin (If Not Already Enabled)

Shares USDC margin across perps + HIP-3 clearinghouses.

```bash
unified-margin
```

### 5. Connect (start trading session)

```bash
connect
```

---

## Returning User Flow (Commands In Terminal)


```bash
connect
```

---

## Trading

### Place a limit order

```bash
buy or sell
```

### Place a stop-loss / take-profit

```bash
tp or sl
```

### Cancel an order

```bash
cancel
```

### Set leverage

```bash
leverage
```

---

## Info Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/balance/{address}` | Perps + spot clearinghouse state |
| GET | `/positions/{address}` | Open positions |
| GET | `/orders/{address}` | Open orders |
| GET | `/fills/{address}` | Recent trade fills |
| GET | `/agents/{address}` | Approved agents |
| GET | `/prices` | All current mid prices |
| GET | `/meta` | Exchange metadata (all listed assets) |
| GET | `/health` | Server health check |

```bash
# Check balance
curl http://api.hlos.app/balance/0xYOUR_ADDRESS

# View positions
curl http://api.hlos.app/positions/0xYOUR_ADDRESS

# View open orders
curl http://api.hlos.app/orders/0xYOUR_ADDRESS

# Get all prices
curl http://api.hlos.app/prices
```

---

## Full Endpoint Reference

### Setup

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/agent/create` | — | Generate agent EOA |
| POST | `/agent/approve` | `main_private_key`, `agent_address` | Approve agent on HL L1 |
| POST | `/builder/approve` | `main_private_key` | Approve builder fee |
| POST | `/margin/unified` | `main_private_key`, `enabled` | Toggle unified margin |
| POST | `/connect` | `user_address`, `agent_private_key` | Start trading session |

### Trading

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/order/limit` | `user_address`, `asset`, `is_buy`, `price`, `size`, `leverage?`, `tif?`, `reduce_only?` | Limit order |
| POST | `/order/trigger` | `user_address`, `asset`, `is_buy`, `trigger_price`, `size`, `tpsl` | TP/SL trigger |
| POST | `/order/cancel` | `user_address`, `asset`, `oid` | Cancel order |
| POST | `/leverage` | `user_address`, `asset`, `leverage`, `is_cross?` | Set leverage |

### Info

| Method | Path | Description |
|--------|------|-------------|
| GET | `/balance/{address}` | Balances + margin |
| GET | `/positions/{address}` | Open positions |
| GET | `/orders/{address}` | Open orders |
| GET | `/fills/{address}` | Recent fills |
| GET | `/agents/{address}` | Approved agents |
| GET | `/prices` | All mid prices |
| GET | `/meta` | Asset metadata |
| GET | `/health` | Health check |

---

## Configuration

Copy `.env.example` to `.env` to override defaults:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `HL_API_BASE` | `https://api.hyperliquid.xyz` | Hyperliquid API base URL |
| `PORT` | `8000` | Server port |

---

## License

MIT
