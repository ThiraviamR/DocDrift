# Inventory API

A small FastAPI service that tracks stock across warehouses.

## Quickstart

```bash
pip install -r requirements.txt
export INV_DB_URL=sqlite:///inventory.db
uvicorn app.main:app --reload
```

Check it is up:

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/v1/stock?limit=10"
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `INV_DB_URL` | `sqlite:///inventory.db` | Database connection string |

## Contributing

Open a pull request against `main`. Keep endpoints backwards compatible where you can.
