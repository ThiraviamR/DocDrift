"""Inventory API — sample service used to demo DocDrift."""
import os

from fastapi import FastAPI, HTTPException

DB_URL = os.getenv("INVENTORY_DATABASE_URL", "sqlite:///inventory.db")
DEFAULT_PAGE_SIZE = 50
MAX_RESERVATION_QTY = 100

app = FastAPI(title="Inventory API")

_STOCK = {
    "SKU-1001": {"name": "Widget", "warehouse": "BLR-1", "on_hand": 40},
    "SKU-1002": {"name": "Gadget", "warehouse": "BLR-2", "on_hand": 12},
}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/inventory")
def list_stock(page_size: int = DEFAULT_PAGE_SIZE, warehouse: str | None = None):
    items = [
        {"sku": sku, **item}
        for sku, item in _STOCK.items()
        if warehouse is None or item["warehouse"] == warehouse
    ]
    return {"items": items[:page_size], "count": len(items)}


@app.get("/v1/inventory/{sku}")
def get_stock_item(sku: str):
    if sku not in _STOCK:
        raise HTTPException(status_code=404, detail="SKU not found")
    return {"sku": sku, **_STOCK[sku]}


@app.post("/v1/inventory/{sku}/reserve")
def reserve_stock(sku: str, quantity: int, hold_minutes: int = 15):
    if quantity > MAX_RESERVATION_QTY:
        raise HTTPException(status_code=422, detail="quantity too large")
    if sku not in _STOCK or _STOCK[sku]["on_hand"] < quantity:
        raise HTTPException(status_code=409, detail="insufficient stock")
    return {"sku": sku, "reserved": quantity, "expires_in_minutes": hold_minutes}
