import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

import requests as _requests

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
    )

    store = Store(data={"StoreID": state.store_id}, country=config.address.country)
    order = PizzaOrder(store, customer, address, country=config.address.country)

    # Fix hardcoded US values in pizzapi for Canadian orders
    if config.address.country.lower() == "ca":
        order.data["SourceOrganizationURI"] = "order.dominos.ca"
        order.data["Market"] = "CANADA"

        # Monkey-patch _send to use the Canadian Referer header
        import types

        def _ca_send(self, url, merge):
            self.data.update(
                StoreID=self.store.id,
                Email=self.customer.email,
                FirstName=self.customer.first_name,
                LastName=self.customer.last_name,
                Phone=self.customer.phone,
            )
            for key in ("Products", "StoreID", "Address"):
                if key not in self.data or not self.data[key]:
                    raise Exception('order has invalid value for key "%s"' % key)

            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "Referer": "https://order.dominos.ca/en/pages/order/",
                "Origin": "https://order.dominos.ca",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "DPZ-Language": "en",
                "DPZ-Market": "CANADA",
            }
            r = _requests.post(url=url, headers=headers, json={"Order": self.data})
            r.raise_for_status()
            json_data = r.json()
            if merge:
                for key, value in json_data["Order"].items():
                    if value or not isinstance(value, list):
                        self.data[key] = value
            return json_data

        order._send = types.MethodType(_ca_send, order)

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


def _estimate_price_from_products(products: list, tax_rate: float = 0.15, delivery_fee: float = 4.99) -> dict:
    """Estimate pricing from product Pricing data returned by validate()."""
    subtotal = 0.0
    for p in products:
        pricing = p.get("Pricing", {})
        # Price1-0 = base price with 0 extra toppings
        try:
            base = float(pricing.get("Price1-0", 0))
        except (ValueError, TypeError):
            base = 0.0
        qty = p.get("Qty", 1)
        subtotal += base * qty
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax + delivery_fee, 2)
    return {
        "subtotal": round(subtotal, 2),
        "tax": tax,
        "delivery_fee": delivery_fee,
        "discount": 0,
        "total": total,
        "note": "Estimated pricing. Actual total confirmed at time of order.",
    }


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
        # Capture product pricing BEFORE validate() overwrites Products
        products_with_pricing = [dict(p) for p in order.data.get("Products", [])]
        order.validate()

        estimate = order.data.get("EstimatedWaitMinutes", "")
        pricing = _estimate_price_from_products(products_with_pricing)

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
                order.data["FutureOrderTime"] = formatted_scheduled
            except ValueError:
                _audit_log(
                    f"PLACE_ORDER | ABORTED | reason=INVALID_TIME | time={scheduled_time}"
                )
                return {
                    "success": False,
                    "error": f"Invalid scheduled_time format: {scheduled_time}. Use ISO 8601 (e.g. 2026-02-27T18:30:00).",
                    "code": "INVALID_TIME",
                }

        # Capture product pricing BEFORE validate() overwrites Products
        products_with_pricing = [dict(p) for p in order.data.get("Products", [])]
        order.validate()
        # Re-apply CA overrides after validate() merges the response
        if config.address.country.lower() == "ca":
            order.data["Market"] = "CANADA"
            order.data["SourceOrganizationURI"] = "order.dominos.ca"
        pricing = _estimate_price_from_products(products_with_pricing)
        total = pricing["total"]
        if tip_amount > 0:
            total = round(total + tip_amount, 2)

        # Layer 3: Max amount check
        max_amount = config.preferences.max_order_amount_cad
        if max_amount and total > max_amount:
            _audit_log(
                f"PLACE_ORDER | ABORTED | reason=OVER_MAX | total={total} | max={max_amount}"
            )
            return {
                "success": False,
                "error": f"Order total ~${total:.2f} exceeds max ${max_amount:.2f}",
                "code": "OVER_MAX",
            }

        item_summary = [f"{item.code} x{item.quantity}" for item in state.cart]

        # Layer 4: Dry run
        if dry_run:
            _audit_log(
                f"PLACE_ORDER | DRY_RUN | store={state.store_id} | "
                f"items={json.dumps(item_summary)} | estimated_total={total}"
                + (f" | scheduled={formatted_scheduled}" if formatted_scheduled else "")
            )
            state.cart.clear()
            return {
                "success": True,
                "order_id": "DRY_RUN_NO_ORDER",
                "dry_run": True,
                "estimated_total": total,
                "scheduled_for": formatted_scheduled,
                "message": "DRY RUN — order was NOT placed. Set DRY_RUN=false to place real orders.",
            }

        # Place the real order
        if config.payment.pay_at_door:
            # Cash / pay at door — set payment manually and skip the price URL call
            if tip_amount > 0:
                order.data["Amounts"] = order.data.get("Amounts", {})
                order.data["Amounts"]["Tip"] = tip_amount
            order.data["Payments"] = [{"Type": "Cash"}]
            result = order._send(order.urls.place_url(), False)
        else:
            card = PaymentObject(
                config.payment.card_number,
                config.payment.expiration,
                config.payment.cvv,
                config.payment.billing_postal_code,
            )
            if tip_amount > 0:
                order.data["Amounts"] = order.data.get("Amounts", {})
                order.data["Amounts"]["Tip"] = tip_amount
            result = order.place(card)

        # Check place result status
        if isinstance(result, dict) and result.get("Status") == -1:
            raise Exception(f"Place order failed: {result}")

        # Order ID from result (merge=False) or fallback to order.data
        result_order = result.get("Order", {}) if isinstance(result, dict) else {}
        order_id = (
            result_order.get("OrderID")
            or result_order.get("AdvanceOrderID")
            or order.data.get("OrderID")
            or order.data.get("AdvanceOrderID", "UNKNOWN")
        )

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
