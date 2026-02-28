import logging
from typing import Any, Optional

from dominos_mcp.config import DominosConfig
from dominos_mcp.state import CartItem, ServerState

logger = logging.getLogger(__name__)


async def get_cart(
    state: ServerState,
    config: DominosConfig,
) -> dict[str, Any]:
    """View the current cart contents and running total."""
    items = []
    for i, item in enumerate(state.cart):
        items.append(
            {
                "cart_index": i,
                "code": item.code,
                "quantity": item.quantity,
                "options": item.options,
                "special_instructions": item.special_instructions,
            }
        )

    return {
        "success": True,
        "store_id": state.store_id,
        "items": items,
        "item_count": len(state.cart),
    }


async def add_to_cart(
    state: ServerState,
    config: DominosConfig,
    item_code: str,
    quantity: int = 1,
    options: Optional[dict] = None,
    special_instructions: str = "",
) -> dict[str, Any]:
    """Add an item to the current order."""
    try:
        sid = state.store_id or (str(config.preferences.preferred_store_id) if getattr(config.preferences, "preferred_store_id", None) else None)
        state.store_id = sid
        if not state.store_id:
            return {
                "success": False,
                "error": "No store selected. Call find_nearby_stores first.",
                "code": "NO_STORE",
            }

        if quantity < 1 or quantity > 10:
            return {
                "success": False,
                "error": "Quantity must be between 1 and 10.",
                "code": "INVALID_QUANTITY",
            }

        cart_item = CartItem(
            code=item_code,
            quantity=quantity,
            options=options or {},
            special_instructions=special_instructions,
        )
        state.cart.append(cart_item)
        state.save()

        cart_index = len(state.cart) - 1

        return {
            "success": True,
            "cart_index": cart_index,
            "item": {
                "code": item_code,
                "quantity": quantity,
                "options": cart_item.options,
            },
            "cart_total_items": len(state.cart),
        }

    except Exception as e:
        logger.exception("Error adding to cart")
        return {"success": False, "error": str(e), "code": "ADD_FAILED"}


async def remove_from_cart(
    state: ServerState,
    config: DominosConfig,
    cart_index: int,
) -> dict[str, Any]:
    """Remove an item from the cart by its cart index."""
    try:
        if cart_index < 0 or cart_index >= len(state.cart):
            return {
                "success": False,
                "error": f"Invalid cart index {cart_index}. Cart has {len(state.cart)} items.",
                "code": "INVALID_INDEX",
            }

        removed = state.cart.pop(cart_index)
        return {
            "success": True,
            "removed_item": removed.code,
            "cart_total_items": len(state.cart),
        }

    except Exception as e:
        logger.exception("Error removing from cart")
        return {"success": False, "error": str(e), "code": "REMOVE_FAILED"}


async def clear_cart(
    state: ServerState,
    config: DominosConfig,
) -> dict[str, Any]:
    """Empty the entire cart and clear the selected store."""
    state.cart.clear()
    state.store_id = None
    state.save()
    state.store_info = {}
    return {"success": True, "message": "Cart cleared."}
