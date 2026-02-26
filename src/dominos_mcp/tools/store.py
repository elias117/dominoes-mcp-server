import json
import logging
from typing import Any, Optional

from pizzapi import Address as PizzaAddress
from pizzapi import Store

from dominos_mcp.config import DominosConfig
from dominos_mcp.state import ServerState

logger = logging.getLogger(__name__)


def _make_address(
    street: str, city: str, region: str, postal_code: str, country: str = "ca"
) -> PizzaAddress:
    return PizzaAddress(street, city, region, postal_code, country=country)


async def find_nearby_stores(
    state: ServerState,
    config: DominosConfig,
    street: str = "",
    city: str = "",
    region: str = "",
    postal_code: str = "",
    order_type: str = "Delivery",
) -> dict[str, Any]:
    """Find Domino's stores near a given address. Returns stores sorted by distance."""
    try:
        s = street or config.address.street
        c = city or config.address.city
        r = region or config.address.region
        p = postal_code or config.address.postal_code
        country = config.address.country

        address = _make_address(s, c, r, p, country)
        results = address.nearby_stores(service=order_type)

        # results is a list of Store objects
        stores = []
        for store_obj in results[:5]:
            d = store_obj.data
            store_id = str(d.get("StoreID", store_obj.id))
            is_open = d.get("IsOnlineNow", False) and d.get("AllowDeliveryOrders", False)
            service_info = d.get("ServiceMethodEstimatedWaitMinutes", {})
            delivery_info = service_info.get("Delivery", {})

            stores.append(
                {
                    "store_id": store_id,
                    "address": d.get("AddressDescription", "").strip(),
                    "phone": d.get("Phone", ""),
                    "is_open": is_open,
                    "delivery_minutes_min": delivery_info.get("Min", None),
                    "delivery_minutes_max": delivery_info.get("Max", None),
                    "minimum_delivery_order_amount": d.get(
                        "MinimumDeliveryOrderAmount", None
                    ),
                }
            )

        # Auto-select closest open store
        for store in stores:
            if store["is_open"]:
                state.store_id = store["store_id"]
                break

        return {"success": True, "stores": stores}

    except Exception as e:
        logger.exception("Error finding nearby stores")
        return {"success": False, "error": str(e), "code": "STORE_LOOKUP_FAILED"}


async def get_menu(
    state: ServerState,
    config: DominosConfig,
    store_id: str = "",
    category: str = "All",
) -> dict[str, Any]:
    """Get the full menu for a store. Returns categorized menu items."""
    try:
        sid = store_id or state.store_id
        if not sid:
            return {
                "success": False,
                "error": "No store selected. Call find_nearby_stores first.",
                "code": "NO_STORE",
            }

        # Check cache
        if sid in state.menu_cache:
            menu_data = state.menu_cache[sid]
        else:
            store = Store(store_id=sid, country=config.address.country)
            menu = store.get_menu()
            menu_data = _parse_menu(menu)
            state.menu_cache[sid] = menu_data

        if category != "All" and category in menu_data:
            filtered = {category: menu_data[category]}
        elif category != "All":
            filtered = {category: []}
        else:
            filtered = menu_data

        return {"success": True, "store_id": sid, "categories": filtered}

    except Exception as e:
        logger.exception("Error fetching menu")
        return {"success": False, "error": str(e), "code": "MENU_FETCH_FAILED"}


def _parse_menu(menu) -> dict[str, list[dict]]:
    """Parse pizzapi Menu object into categorized items."""
    categories: dict[str, list[dict]] = {}

    category_map = {
        "Pizza": ["Pizza"],
        "Wings": ["Wings", "Wing"],
        "Pasta": ["Pasta"],
        "Bread": ["Bread", "Breadsticks"],
        "Drinks": ["Drinks", "Beverage", "Coke", "Sprite"],
        "Desserts": ["Desserts", "Dessert"],
    }

    try:
        variants = menu.variants if hasattr(menu, "variants") else {}
        if not isinstance(variants, dict):
            variants = {}

        for code, item in variants.items():
            if not isinstance(item, dict):
                continue

            name = item.get("Name", "")
            price = item.get("Price", "")
            product_type = item.get("ProductType", "")
            tags = item.get("Tags", {})

            # Determine category
            item_category = "Other"
            for cat_name, keywords in category_map.items():
                if any(
                    kw.lower() in product_type.lower()
                    or kw.lower() in name.lower()
                    or kw.lower() in str(tags).lower()
                    for kw in keywords
                ):
                    item_category = cat_name
                    break

            if item_category not in categories:
                categories[item_category] = []

            categories[item_category].append(
                {
                    "code": code,
                    "name": name,
                    "price": price,
                    "description": item.get("Description", ""),
                }
            )

        # Also parse coupons
        coupons = menu.coupons if hasattr(menu, "coupons") else {}
        if isinstance(coupons, dict) and coupons:
            categories["Coupons"] = []
            for code, coupon in coupons.items():
                if not isinstance(coupon, dict):
                    continue
                categories["Coupons"].append(
                    {
                        "code": code,
                        "name": coupon.get("Name", ""),
                        "price": coupon.get("Price", ""),
                        "description": coupon.get("Description", ""),
                    }
                )
    except Exception as e:
        logger.warning(f"Error parsing menu structure: {e}")
        # Fallback: try to use menu.data directly
        try:
            raw = menu.data if hasattr(menu, "data") else {}
            if isinstance(raw, dict):
                for code, item in raw.get("Variants", {}).items():
                    if not isinstance(item, dict):
                        continue
                    cat = "Other"
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append(
                        {
                            "code": code,
                            "name": item.get("Name", code),
                            "price": item.get("Price", ""),
                            "description": "",
                        }
                    )
        except Exception:
            pass

    return categories


async def search_menu_items(
    state: ServerState,
    config: DominosConfig,
    query: str,
    store_id: str = "",
) -> dict[str, Any]:
    """Search for specific items in the store menu by name or description."""
    try:
        sid = store_id or state.store_id
        if not sid:
            return {
                "success": False,
                "error": "No store selected. Call find_nearby_stores first.",
                "code": "NO_STORE",
            }

        store = Store(store_id=sid, country=config.address.country)
        menu = store.get_menu()

        # Cache while we have it
        if sid not in state.menu_cache:
            state.menu_cache[sid] = _parse_menu(menu)

        # Search through variants
        results = []
        query_lower = query.lower()
        variants = menu.variants if hasattr(menu, "variants") else {}
        if not isinstance(variants, dict):
            variants = {}

        for code, item in variants.items():
            if not isinstance(item, dict):
                continue
            name = item.get("Name", "")
            description = item.get("Description", "")
            if query_lower in name.lower() or query_lower in description.lower():
                results.append(
                    {
                        "code": code,
                        "name": name,
                        "category": item.get("ProductType", ""),
                        "price": item.get("Price", ""),
                        "description": description,
                    }
                )

        # Cap at 20 results
        results = results[:20]

        return {"success": True, "results": results, "result_count": len(results)}

    except Exception as e:
        logger.exception("Error searching menu")
        return {"success": False, "error": str(e), "code": "SEARCH_FAILED"}
