# API Reference

All endpoints return JSON.

## List stock

`GET /v1/stock`

| Query param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 20 | Maximum number of items to return |
| `warehouse` | str | – | Filter by warehouse code, e.g. `BLR-1` |

Example:

```python
import requests

resp = requests.get("http://localhost:8000/v1/stock", params={"limit": 5, "warehouse": "BLR-1"})
print(resp.json()["items"])
```

## Get a single item

`GET /v1/stock/{sku}` returns one item or `404` if the SKU is unknown.

```bash
curl http://localhost:8000/v1/stock/SKU-1001
```

## Reserve stock

`POST /v1/stock/{sku}/reserve?quantity=3&ttl_minutes=30`

Holds stock for an order. The reservation expires after `ttl_minutes` (default 15).
Requests above 100 units are rejected with `422`; insufficient stock returns `409`.

## Health

`GET /health` returns `{"status": "ok"}`.
