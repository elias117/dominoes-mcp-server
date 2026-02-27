import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP, Context

from dominos_mcp.config import DominosConfig, load_config
from dominos_mcp.state import ServerState
from dominos_mcp.tools.cart import add_to_cart, clear_cart, get_cart, remove_from_cart
from dominos_mcp.tools.order import place_order, price_order, validate_order
from dominos_mcp.tools.store import find_nearby_stores, get_menu, search_menu_items

# Configure logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Initialize server state and config on startup."""
    logger.info("Starting Domino's MCP server...")

    try:
        config = load_config()
        logger.info("Config loaded successfully")
    except FileNotFoundError as e:
        logger.error(str(e))
        raise

    state = ServerState()

    yield {"config": config, "state": state}

    logger.info("Shutting down Domino's MCP server")


host = os.environ.get("HOST", "0.0.0.0")
port = int(os.environ.get("PORT", "8000"))

mcp = FastMCP(
    "Domino's Pizza MCP Server",
    lifespan=lifespan,
    host=host,
    port=port,
)


def _get_deps(ctx) -> tuple[ServerState, DominosConfig]:
    """Extract state and config from the MCP context."""
    state = ctx.request_context.lifespan_context["state"]
    config = ctx.request_context.lifespan_context["config"]
    return state, config


# --- Store Tools ---


@mcp.tool()
async def tool_find_nearby_stores(
    ctx: Context,
    street: str = "",
    city: str = "",
    region: str = "",
    postal_code: str = "",
    order_type: str = "Delivery",
) -> str:
    """Find Domino's stores near a given address. Returns stores sorted by distance.
    Should be called first to select a store before browsing menu or building an order.
    All address fields are optional — omit to use your default address from config."""
    state, config = _get_deps(ctx)
    result = await find_nearby_stores(
        state, config, street, city, region, postal_code, order_type
    )
    return json.dumps(result)


@mcp.tool()
async def tool_get_menu(
    ctx: Context,
    store_id: str = "",
    category: str = "All",
) -> str:
    """Get the full menu for the currently selected store (or a specified store).
    Returns categorized menu items. Categories: Pizza, Wings, Pasta, Bread, Drinks, Desserts, Coupons, All."""
    state, config = _get_deps(ctx)
    result = await get_menu(state, config, store_id, category)
    return json.dumps(result)


@mcp.tool()
async def tool_search_menu_items(
    ctx: Context,
    query: str,
    store_id: str = "",
) -> str:
    """Search for specific items in the store menu by name or description.
    More focused than get_menu — use this when the user asks for something specific
    like 'pepperoni pizza' or 'buffalo wings'."""
    state, config = _get_deps(ctx)
    result = await search_menu_items(state, config, query, store_id)
    return json.dumps(result)


# --- Cart Tools ---


@mcp.tool()
async def tool_get_cart(ctx: Context) -> str:
    """View the current cart contents and running total."""
    state, config = _get_deps(ctx)
    result = await get_cart(state, config)
    return json.dumps(result)


@mcp.tool()
async def tool_add_to_cart(
    ctx: Context,
    item_code: str,
    quantity: int = 1,
    options: Optional[dict] = None,
    special_instructions: str = "",
) -> str:
    """Add an item to the current order. Use search_menu_items to find valid item codes first.
    Options format for toppings: {"P": {"1/1": "1"}} adds pepperoni full coverage.
    Quantity must be 1-10."""
    state, config = _get_deps(ctx)
    result = await add_to_cart(
        state, config, item_code, quantity, options, special_instructions
    )
    return json.dumps(result)


@mcp.tool()
async def tool_remove_from_cart(ctx: Context, cart_index: int) -> str:
    """Remove an item from the cart by its cart index (from get_cart response)."""
    state, config = _get_deps(ctx)
    result = await remove_from_cart(state, config, cart_index)
    return json.dumps(result)


@mcp.tool()
async def tool_clear_cart(ctx: Context) -> str:
    """Empty the entire cart. Also clears the selected store."""
    state, config = _get_deps(ctx)
    result = await clear_cart(state, config)
    return json.dumps(result)


# --- Order Tools ---


@mcp.tool()
async def tool_price_order(ctx: Context) -> str:
    """Get the full pricing breakdown for the current cart including taxes and fees.
    Does NOT place the order. Use this before place_order to show the user what they'll pay."""
    state, config = _get_deps(ctx)
    result = await price_order(state, config)
    return json.dumps(result)


@mcp.tool()
async def tool_validate_order(ctx: Context) -> str:
    """Validate the current order without placing it. Checks item availability,
    delivery address, minimum order amount. Returns any validation errors."""
    state, config = _get_deps(ctx)
    result = await validate_order(state, config)
    return json.dumps(result)


@mcp.tool()
async def tool_place_order(
    ctx: Context,
    confirm_order: str,
    tip_amount: float = 0,
    scheduled_time: str = "",
) -> str:
    """PLACES A REAL ORDER AND CHARGES YOUR CARD. Requires explicit confirmation.
    Call price_order and validate_order first.
    The confirm_order parameter must be exactly 'YES_PLACE_MY_ORDER' to proceed.
    tip_amount is in CAD (e.g. 3.00). Default: 0.
    scheduled_time is optional ISO 8601 format (e.g. '2026-02-27T18:30:00') for future delivery.
    Must be at least 30 minutes in the future. If omitted, order is placed for ASAP delivery."""
    state, config = _get_deps(ctx)
    result = await place_order(state, config, confirm_order, tip_amount, scheduled_time)
    return json.dumps(result)



if __name__ == "__main__":
    logger.info(f"Starting MCP server on {host}:{port}")
    mcp.run(transport="streamable-http")
