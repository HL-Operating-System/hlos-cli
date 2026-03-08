# hlos-cli

FastAPI server for agent-based trading on [Hyperliquid](https://hyperliquid.xyz) via the [rePRICE / HLOS](https://hlos.app) platform.

Built for AI agents, trading bots, and developers who want programmatic access to Hyperliquid perpetuals through a simple REST API.

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

Server starts at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Docker

```bash
docker build -t hlos-cli .
docker run -p 8000:8000 hlos-cli
```

---

## How It Works

Hyperliquid uses an **agent wallet** pattern: your main wallet approves a secondary EOA (the "agent") that can trade on its behalf without requiring your main key for every order.

**New users** go through a one-time setup, then trade via the agent. **Returning users** skip straight to `/connect`.

---

## New User Flow

### 1. Generate an agent wallet

```bash
curl -X POST http://localhost:8000/agent/create
```

Returns `agent_address` and `agent_private_key`. **Save the private key.**

### 2. Approve the agent on Hyperliquid L1

```bash
curl -X POST http://localhost:8000/agent/approve \
  -H "Content-Type: application/json" \
  -d '{
    "main_private_key": "0xYOUR_MAIN_WALLET_KEY",
    "agent_address": "0xAGENT_ADDRESS_FROM_STEP_1"
  }'
```

### 3. Approve builder fee

```bash
curl -X POST http://localhost:8000/builder/approve \
  -H "Content-Type: application/json" \
  -d '{"main_private_key": "0xYOUR_MAIN_WALLET_KEY"}'
```

### 4. (Optional) Enable unified margin

Shares USDC margin across perps + HIP-3 clearinghouses.

```bash
curl -X POST http://localhost:8000/margin/unified \
  -H "Content-Type: application/json" \
  -d '{"main_private_key": "0xYOUR_MAIN_WALLET_KEY", "enabled": true}'
```

### 5. Connect (start trading session)

```bash
curl -X POST http://localhost:8000/connect \
  -H "Content-Type: application/json" \
  -d '{
    "user_address": "0xYOUR_MAIN_WALLET",
    "agent_private_key": "0xAGENT_PRIVATE_KEY"
  }'
```

---

## Returning User Flow

If you already have an approved agent, skip to step 5:

```bash
curl -X POST http://localhost:8000/connect \
  -H "Content-Type: application/json" \
  -d '{
    "user_address": "0xYOUR_MAIN_WALLET",
    "agent_private_key": "0xAGENT_PRIVATE_KEY"
  }'
```

---

## Trading

### Place a limit order

```bash
curl -X POST http://localhost:8000/order/limit \
  -H "Content-Type: application/json" \
  -d '{
    "user_address": "0xYOUR_MAIN_WALLET",
    "asset": "BTC",
    "is_buy": true,
    "price": 90000,
    "size": 0.01,
    "leverage": 10,
    "tif": "Gtc"
  }'
```

### Place a stop-loss / take-profit

```bash
curl -X POST http://localhost:8000/order/trigger \
  -H "Content-Type: application/json" \
  -d '{
    "user_address": "0xYOUR_MAIN_WALLET",
    "asset": "BTC",
    "is_buy": false,
    "trigger_price": 85000,
    "size": 0.01,
    "tpsl": "sl"
  }'
```

### Cancel an order

```bash
curl -X POST http://localhost:8000/order/cancel \
  -H "Content-Type: application/json" \
  -d '{
    "user_address": "0xYOUR_MAIN_WALLET",
    "asset": "BTC",
    "oid": 123456
  }'
```

### Set leverage

```bash
curl -X POST http://localhost:8000/leverage \
  -H "Content-Type: application/json" \
  -d '{
    "user_address": "0xYOUR_MAIN_WALLET",
    "asset": "ETH",
    "leverage": 20,
    "is_cross": true
  }'
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
curl http://localhost:8000/balance/0xYOUR_ADDRESS

# View positions
curl http://localhost:8000/positions/0xYOUR_ADDRESS

# View open orders
curl http://localhost:8000/orders/0xYOUR_ADDRESS

# Get all prices
curl http://localhost:8000/prices
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
