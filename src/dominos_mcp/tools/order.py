import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from pizzapi import Address as PizzaAddress
from pizzapi import Customer as PizzaCustomer
from pizzapi import Order as PizzaOrder
from pizzapi import PaymentObject, Store

from dominos_mcp.config import DominosConfig
from dominos_mcp.state import ServerState

logger = logging.getLogger(__name__)

LOG_PATH = os.environ.get("LOG_PATH", "/data/orders.log")


def _build_order(state: ServerState, config: DominosConfig) -> PizzaOrder:
    """Build a pizzapi Order from current state and config."""
    address = PizzaAddress(
        config.address.street,
        config.address.city,
        config.address.region,
        config.address.postal_code,
        country=config.address.country,
    )

    customer = PizzaCustomer(
        config.customer.first_name,
        config.customer.last_name,
        config.customer.email,
        config.customer.phone,
        address,
    )

    store = Store(store_id=state.store_id, country=config.address.country)
    order = PizzaOrder(store, customer, address, country=config.address.country)

    for item in state.cart:
        for _ in range(item.quantity):
            order.add_item(item.code, options=item.options if item.options else {})

    return order


def _audit_log(message: str) -> None:
    """Append an entry to the audit log."""
    try:
        log_dir = os.path.dirname(LOG_PATH)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(LOG_PATH, "a") as f:
            f.write(f"{timestamp} | {message}\n")
    except Exception as e:
        logger.warning(f"Failed to write audit log: {e}")


async def price_order(
    state: ServerState,
    config: DominosConfig,
) -> dict[str, Any]:
    """Get the full pricing breakdown for the current cart including taxes and fees."""
    try:
        if not state.store_id:
            return {
                "success": False,
                "error": "No store selected. Call find_nearby_stores first.",
                "code": "NO_STORE",
            }

        if not state.cart:
            return {
                "success": False,
                "error": "Cart is empty. Add items first.",
                "code": "EMPTY_CART",
            }

        order = _build_order(state, config)
        order.price()

        amounts = order.data.get("Order", {}).get("Amounts", {})
        estimate = order.data.get("Order", {}).get(
            "EstimatedWaitMinutes", ""
        )

        pricing = {
            "subtotal": amounts.get("Menu", 0),
            "discount": amounts.get("Discount", 0),
            "surcharge": amounts.get("Surcharge", 0),
            "tax": amounts.get("Tax", 0),
            "delivery_fee": amounts.get("DeliveryFee", 0),
            "total": amounts.get("Customer", 0),
        }

        return {
            "success": True,
            "pricing": pricing,
            "estimated_wait_minutes": estimate,
            "store_id": state.store_id,
        }

    except Exception as e:
        logger.exception("Error pricing order")
        return {"success": False, "error": str(e), "code": "PRICE_FAILED"}


async def validate_order(
    state: ServerState,
    config: DominosConfig,
) -> dict[str, Any]:
    """Validate the current order without placing it."""
    try:
        if not state.store_id:
            return {
                "success": False,
                "error": "No store selected. Call find_nearby_stores first.",
                "code": "NO_STORE",
            }

        if not state.cart:
            return {
                "success": False,
                "error": "Cart is empty. Add items first.",
                "code": "EMPTY_CART",
            }

        order = _build_order(state, config)
        order.validate()

        status = order.data.get("Status", -1)
        status_items = order.data.get("Order", {}).get("StatusItems", [])

        errors = []
        warnings = []
        for item in status_items:
            if isinstance(item, dict):
                code = item.get("Code", "")
                if item.get("PulseCode", 0) == 1:
                    errors.append(code)
                else:
                    warnings.append(code)

        is_valid = status >= 0 and len(errors) == 0

        return {
            "success": True,
            "valid": is_valid,
            "warnings": warnings,
            "errors": errors,
        }

    except Exception as e:
        logger.exception("Error validating order")
        error_msg = str(e)
        return {
            "success": True,
            "valid": False,
            "errors": [error_msg],
            "warnings": [],
        }


async def place_order(
    state: ServerState,
    config: DominosConfig,
    confirm_order: str,
    tip_amount: float = 0,
    scheduled_time: str = "",
) -> dict[str, Any]:
    """Place a real order. Requires confirm_order='YES_PLACE_MY_ORDER'."""
    dry_run = os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes")

    # Layer 1+2: Confirmation check
    if confirm_order != "YES_PLACE_MY_ORDER":
        _audit_log("PLACE_ORDER | ABORTED | reason=NOT_CONFIRMED")
        return {
            "success": False,
            "error": "Order not confirmed. Pass confirm_order='YES_PLACE_MY_ORDER' to proceed.",
            "code": "NOT_CONFIRMED",
        }

    if not state.store_id:
        _audit_log("PLACE_ORDER | ABORTED | reason=NO_STORE")
        return {
            "success": False,
            "error": "No store selected. Call find_nearby_stores first.",
            "code": "NO_STORE",
        }

    if not state.cart:
        _audit_log("PLACE_ORDER | ABORTED | reason=EMPTY_CART")
        return {
            "success": False,
            "error": "Cart is empty. Add items first.",
            "code": "EMPTY_CART",
        }

    try:
        order = _build_order(state, config)

        # Set tip
        if tip_amount > 0:
            order.data["Order"]["Amounts"] = order.data.get("Order", {}).get(
                "Amounts", {}
            )
            order.data["Order"]["Amounts"]["Tip"] = tip_amount

        # Handle scheduled delivery
        formatted_scheduled = None
        if scheduled_time:
            try:
                dt = datetime.fromisoformat(scheduled_time)
                now = datetime.now()
                if dt < now + timedelta(minutes=30):
                    _audit_log(
                        f"PLACE_ORDER | ABORTED | reason=SCHEDULED_TOO_SOON | time={scheduled_time}"
                    )
                    return {
                        "success": False,
                        "error": "Scheduled time must be at least 30 minutes in the future.",
                        "code": "SCHEDULED_TOO_SOON",
                    }
                formatted_scheduled = dt.strftime("%Y-%m-%d %H:%M:%S")
                order.data["Order"]["FutureOrderTime"] = formatted_scheduled
            except ValueError:
                _audit_log(
                    f"PLACE_ORDER | ABORTED | reason=INVALID_TIME | time={scheduled_time}"
                )
                return {
                    "success": False,
                    "error": f"Invalid scheduled_time format: {scheduled_time}. Use ISO 8601 (e.g. 2026-02-27T18:30:00).",
                    "code": "INVALID_TIME",
                }

        # Price the order to get total
        order.price()
        amounts = order.data.get("Order", {}).get("Amounts", {})
        total = amounts.get("Customer", 0)
        if isinstance(total, str):
            try:
                total = float(total)
            except ValueError:
                total = 0

        # Layer 3: Max amount check
        max_amount = config.preferences.max_order_amount_cad
        if max_amount and total > max_amount:
            _audit_log(
                f"PLACE_ORDER | ABORTED | reason=OVER_MAX | total={total} | max={max_amount}"
            )
            return {
                "success": False,
                "error": f"Order total ${total:.2f} exceeds max ${max_amount:.2f}",
                "code": "OVER_MAX",
            }

        item_summary = [
            f"{item.code} x{item.quantity}" for item in state.cart
        ]

        # Layer 4: Dry run
        if dry_run:
            _audit_log(
                f"PLACE_ORDER | DRY_RUN | store={state.store_id} | "
                f"items={json.dumps(item_summary)} | total={total}"
                + (f" | scheduled={formatted_scheduled}" if formatted_scheduled else "")
            )
            state.cart.clear()
            return {
                "success": True,
                "order_id": "DRY_RUN_NO_ORDER",
                "dry_run": True,
                "total_charged": total,
                "scheduled_for": formatted_scheduled,
                "message": "DRY RUN — order was NOT placed. Set DRY_RUN=false to place real orders.",
            }

        # Place the real order
        card = PaymentObject(
            config.payment.card_number,
            config.payment.expiration,
            config.payment.cvv,
            config.payment.billing_postal_code,
        )

        order.place(card)

        order_id = order.data.get("Order", {}).get("OrderID", "UNKNOWN")

        _audit_log(
            f"PLACE_ORDER | CONFIRMED | store={state.store_id} | "
            f"items={json.dumps(item_summary)} | total={total} | order_id={order_id}"
            + (f" | scheduled={formatted_scheduled}" if formatted_scheduled else "")
        )

        # Clear cart after successful placement
        state.cart.clear()

        result: dict[str, Any] = {
            "success": True,
            "order_id": order_id,
            "total_charged": total,
        }

        if formatted_scheduled:
            result["scheduled_for"] = formatted_scheduled
            result["message"] = (
                f"Order scheduled for {scheduled_time}. Track with track_order tool."
            )
        else:
            result["message"] = (
                f"Order {order_id} placed successfully. Track with track_order tool."
            )

        return result

    except Exception as e:
        logger.exception("Error placing order")
        _audit_log(f"PLACE_ORDER | ERROR | reason={e}")
        return {"success": False, "error": str(e), "code": "PLACE_FAILED"}
