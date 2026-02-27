import json
import os
from typing import Optional

from pydantic import BaseModel, Field


class Customer(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str


class Address(BaseModel):
    street: str
    unit: str = ""
    city: str
    region: str
    postal_code: str
    country: str = "ca"
    delivery_instructions: str = ""


class Payment(BaseModel):
    card_number: str = ""
    expiration: str = ""  # MM/YY
    cvv: str = ""
    billing_postal_code: str = ""
    pay_at_door: bool = False  # True = cash/card at door (no online payment)


class Preferences(BaseModel):
    order_type: str = "Delivery"
    default_tip_percent: int = 15
    confirm_before_order: bool = True
    max_order_amount_cad: float = 100.00
    preferred_store_id: Optional[str] = None


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"


class DominosConfig(BaseModel):
    customer: Customer
    address: Address
    payment: Payment
    preferences: Preferences = Field(default_factory=Preferences)
    server: ServerConfig = Field(default_factory=ServerConfig)


def load_config(path: Optional[str] = None) -> DominosConfig:
    config_path = path or os.environ.get("CONFIG_PATH", "/config/config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Config file not found at {config_path}. "
            "Copy config.json.example to the config path and fill in your details."
        )
    with open(config_path) as f:
        data = json.load(f)
    return DominosConfig(**data)
