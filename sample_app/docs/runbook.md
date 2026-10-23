# Operations Runbook

## Service won't start: database connection error

1. Confirm `INV_DB_URL` is set in the pod environment: `kubectl exec deploy/inventory -- env | grep INV_DB_URL`
2. Check the database is reachable from the cluster.
3. Restart the deployment once fixed.

## Clients report 429 errors

The API gateway enforces a rate limit of 100 requests per minute per client.
Ask the client to back off and retry; raise the limit only with platform team approval.

## Reservations expiring too early

Reservations expire after the TTL passed by the caller. Check the client is sending
`ttl_minutes` and that it is above the default of 15.
