import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

STATE_PATH = os.environ.get("DOMINOS_STATE_PATH", "/tmp/dominos_cart_state.json")


@dataclass
class CartItem:
    code: str
    quantity: int = 1
    options: dict = field(default_factory=dict)
    special_instructions: str = ""


@dataclass
class ServerState:
    cart: list[CartItem] = field(default_factory=list)
    store_id: Optional[str] = None
    store_info: dict[str, Any] = field(default_factory=dict)
    menu_cache: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self._load()

    def _load(self):
        try:
            if os.path.exists(STATE_PATH):
                with open(STATE_PATH) as f:
                    data = json.load(f)
                self.store_id = data.get("store_id")
                self.cart = [CartItem(**item) for item in data.get("cart", [])]
        except Exception:
            pass

    def save(self):
        try:
            data = {
                "store_id": self.store_id,
                "cart": [asdict(item) for item in self.cart],
            }
            with open(STATE_PATH, "w") as f:
                json.dump(data, f)
        except Exception:
            pass
