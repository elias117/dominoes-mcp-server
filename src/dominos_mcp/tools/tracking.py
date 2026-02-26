import logging
from typing import Any

import requests

from dominos_mcp.config import DominosConfig
from dominos_mcp.state import ServerState

logger = logging.getLogger(__name__)

# Tracking endpoint for Canada
TRACKER_URL = "https://order.dominos.ca/orderstorage/GetTrackerData"


async def track_order(
    state: ServerState,
    config: DominosConfig,
    phone: str = "",
    store_id: str = "",
) -> dict[str, Any]:
    """Track the status of a placed order using the customer's phone number."""
    try:
        phone_number = phone or config.customer.phone
        sid = store_id or state.store_id

        if not phone_number:
            return {
                "success": False,
                "error": "No phone number provided and none in config.",
                "code": "NO_PHONE",
            }

        params: dict[str, str] = {
            "Phone": phone_number.replace("-", "").replace(" ", ""),
            "lang": "en",
        }
        if sid:
            params["StoreID"] = sid

        resp = requests.get(TRACKER_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # Parse tracker response
        orders = data.get("OrderStatuses", [])
        if not orders:
            return {
                "success": True,
                "order_status": "No active orders found",
                "order_description": "No orders are currently being tracked for this phone number.",
            }

        # Return the most recent order status
        latest = orders[0] if orders else {}

        return {
            "success": True,
            "order_status": latest.get("OrderStatus", "Unknown"),
            "order_description": latest.get("OrderDescription", ""),
            "store_id": latest.get("StoreID", ""),
            "order_id": latest.get("OrderID", ""),
            "start_time": latest.get("StartTime", ""),
            "driver_name": latest.get("DriverName", ""),
            "driver_phone": latest.get("DriverPhone", ""),
        }

    except requests.RequestException as e:
        logger.exception("Error tracking order")
        return {"success": False, "error": str(e), "code": "TRACK_FAILED"}
    except Exception as e:
        logger.exception("Error tracking order")
        return {"success": False, "error": str(e), "code": "TRACK_FAILED"}
