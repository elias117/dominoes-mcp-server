# Domino's Pizza MCP Server

An MCP (Model Context Protocol) server that wraps the unofficial Domino's Pizza API. Enables AI assistants to find stores, browse menus, build orders, place orders, and schedule future deliveries — all via MCP tools.

## Features

- **10 MCP tools**: find_nearby_stores, get_menu, search_menu_items, get_cart, add_to_cart, remove_from_cart, clear_cart, price_order, validate_order, place_order
- **Scheduled delivery**: Set a future delivery time via ISO 8601 timestamp
- **Safety gates**: Confirmation string, max order amount guard, DRY_RUN mode
- **Audit logging**: Every place_order attempt logged to `/data/orders.log`
- **Canada support**: Built for Canadian Domino's stores (country='ca')
- **Streamable HTTP transport**: Serves on `POST /mcp` (port 8000)

## Quick Start

### 1. Create config directory

```bash
mkdir -p ~/.config/dominos-mcp
mkdir -p ~/.local/share/dominos-mcp
```

### 2. Set up your config

```bash
cp config.json.example ~/.config/dominos-mcp/config.json
# Edit with your real details:
nano ~/.config/dominos-mcp/config.json
chmod 600 ~/.config/dominos-mcp/config.json
```

### 3. Build and start

```bash
docker compose up -d --build
```

### 4. Verify it's running

```bash
docker compose ps
# Should show "healthy" status
```

### 5. Register with mcporter

```bash
mcporter config add dominosmcp --url http://localhost:8000/mcp --scope home
```

### 6. Verify tools

```bash
mcporter list dominosmcp --schema
# Should list all 10 tools
```

## Usage Examples

### Find nearby stores
```
Call find_nearby_stores with no arguments to use your default address,
or provide street, city, region, postal_code to search a different area.
```

### Order a pizza
```
1. find_nearby_stores → selects closest open store
2. search_menu_items(query="pepperoni pizza") → find item codes
3. add_to_cart(item_code="14SCREEN") → add to cart
4. price_order → see total with taxes
5. place_order(confirm_order="YES_PLACE_MY_ORDER", tip_amount=3.00) → place it
```

### Schedule a future delivery
```
place_order(
  confirm_order="YES_PLACE_MY_ORDER",
  tip_amount=3.00,
  scheduled_time="2026-02-27T18:30:00"
)
```

## Configuration

See `config.json.example` for the full schema. Key sections:

| Section | Purpose |
|---|---|
| `customer` | Name, email, phone for orders |
| `address` | Default delivery address |
| `payment` | Credit card details (never baked into Docker image) |
| `preferences` | Order type, tip %, max amount guard, preferred store |
| `server` | Host, port, log level |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CONFIG_PATH` | `/config/config.json` | Path to config file |
| `LOG_PATH` | `/data/orders.log` | Path to audit log |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `DRY_RUN` | `false` | When `true`, place_order logs but doesn't call Domino's |

## Docker Commands

```bash
# Build and start
docker compose up -d --build

# View logs
docker compose logs -f dominos-mcp

# Stop
docker compose down

# Restart (clears cart state)
docker compose restart dominos-mcp
```

## Security

- Config file is mounted **read-only** into the container
- Port binds to **127.0.0.1 only** (localhost)
- **No secrets** are baked into the Docker image
- `place_order` requires exact confirmation string + max amount guard
- All order attempts are audit-logged
- Set `chmod 600` on your config.json

## Architecture

```
Claude (AI) ←→ MCP/HTTP ←→ dominos-mcp (Docker) ←→ HTTPS ←→ order.dominos.ca
                localhost:8000                              (Unofficial API)
                                    ↑
                                    │ read-only volume
                           ~/.config/dominos-mcp/config.json
```

## Tech Stack

- Python 3.12 + FastMCP (official MCP Python SDK)
- pizzapi (Magicjarvis fork) — unofficial Domino's API wrapper
- Docker (arm64-compatible, python:3.12-slim)
