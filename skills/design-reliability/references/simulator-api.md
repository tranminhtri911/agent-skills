# Payment and notification simulator API

Start (background): `python3 <skill>/scripts/ds.py simulate payment --port 8787 [--state-file sim.json] [--delay-seconds 2] [--webhook-secret whsec_simulator_only]`. It binds to 127.0.0.1, never contacts a real provider, and `livemode` is always `false`.

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/v1/payments` | Header `Idempotency-Key` required. Body `{"amount_minor": int > 0, "currency": "VND", "customer_ref": "c1"}`. Optional `scenario` field or `X-Sim-Scenario` header. `X-Sim-Account` scopes keys per tenant. |
| GET | `/v1/payments/{id}` | Current status (for reconciliation). |
| GET | `/v1/payments?idempotency_key=KEY` | Lookup by operation key. |
| POST | `/v1/refunds` | `Idempotency-Key` required; `{"payment_id", "amount_minor"}`; never above the captured amount. |
| POST | `/v1/messages` | `{"channel": "email|sms|push", "to", "subject", "body"}` stored in the outbox, never sent. |
| GET | `/v1/messages` | Outbox content for assertions. |
| GET | `/_sim/events` | Webhook events emitted so far. |
| POST | `/_sim/webhooks/deliver` | `{"target_url": "http://127.0.0.1:8000/webhooks", "mode": "normal|duplicate|out_of_order", "delay_seconds": 0}` (loopback targets only). |
| POST | `/_sim/reset` | Clear all state. |
| GET | `/_sim/health` | Liveness. |

## Scenarios

| Scenario | Effect |
| --- | --- |
| `success` | 201, payment `succeeded` |
| `decline` | 402 `card_declined`, payment `failed`; replays return the same 402 |
| `success_then_timeout` | payment recorded as succeeded, response is 504 after the delay; retry with the same key returns 201 + `Idempotent-Replayed: true` |
| `timeout_before_processing` | 504 after the delay, nothing recorded, key released |
| `server_error` | 500, nothing recorded, key released |
| `rate_limited` | 429 with `Retry-After: 1`, key released |
| `pending` | 201 with `pending`; becomes `succeeded` after the delay (webhook event emitted) |
| `slow_processing` | key stays `in_progress` during the delay; concurrent retry → 409 `idempotency_key_in_progress` |

Same key + different payload → 409 `idempotency_key_reused`.

## Webhook signature

Header `Sim-Signature: t=<unix>,v1=<hex>` where `v1 = HMAC_SHA256(secret, "<t>." + raw_body)`. Verify on the raw bytes, check the timestamp window, deduplicate by event `id`.

## Point the app at it

Configure the provider base URL through the app's settings/DI for the test profile (e.g. `PAYMENT_API_BASE_URL=http://127.0.0.1:8787`) — never by editing production config.
