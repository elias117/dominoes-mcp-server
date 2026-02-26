from dataclasses import dataclass, field
from typing import Any, Optional


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
