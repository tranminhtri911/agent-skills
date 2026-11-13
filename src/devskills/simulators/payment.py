"""Stateful payment and notification simulator for safe tests (plan §18.4, MONEY-007).

Use it instead of a real provider. It keeps idempotency keys, request
fingerprints and outcomes, and reproduces the failure modes behind double
charges: success with a lost response, concurrent retries, duplicate and
out-of-order webhooks, declines, rate limits and server errors. Messages
(email/SMS/push) go to an in-memory outbox and are never sent anywhere.

HTTP API (JSON, bound to 127.0.0.1 by default):
    POST /v1/payments              Idempotency-Key header required
    GET  /v1/payments/{id}
    GET  /v1/payments?idempotency_key=KEY      lookup for reconciliation
    POST /v1/refunds               Idempotency-Key header required
    POST /v1/messages              outbox only
    GET  /v1/messages
    GET  /_sim/events              webhook events emitted so far
    POST /_sim/webhooks/deliver    {"target_url", "mode": normal|duplicate|out_of_order, "delay_seconds"}
    POST /_sim/reset
    GET  /_sim/health
Scenario: body field "scenario" or header X-Sim-Scenario, one of SCENARIOS.
Tenant scope: optional header X-Sim-Account (idempotency keys are scoped per account).
Webhook signature: header Sim-Signature "t=<unix>,v1=<hex>" where
v1 = HMAC-SHA256(secret, f"{t}.{raw_body}").
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from devskills.fsutil import atomic_write_json

SCENARIOS = (
    "success",
    "decline",
    "success_then_timeout",       # charge recorded, response lost after a delay
    "timeout_before_processing",  # nothing recorded, gateway timeout
    "server_error",               # nothing recorded, 500
    "rate_limited",               # nothing recorded, 429 + Retry-After
    "pending",                    # recorded as pending; succeeds later via webhook
    "slow_processing",            # key stays in_progress for a delay (concurrent retry -> 409)
)
MAX_BODY_BYTES = 64 * 1024
MAX_AMOUNT_MINOR = 10**12
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass
class SimResponse:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)
    # Delay before the response is written; the state change has already happened.
    delay_seconds: float = 0.0


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = {key: value for key, value in payload.items() if key != "scenario"}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PaymentSimulator:
    """Thread-safe in-memory provider with optional JSON persistence for restart tests."""

    def __init__(self, webhook_secret: str = "whsec_simulator_only", delay_seconds: float = 3.0,
                 state_file: Path | None = None, clock=time.time):
        self.webhook_secret = webhook_secret
        self.delay_seconds = delay_seconds
        self.state_file = state_file
        self.clock = clock
        self._lock = threading.RLock()
        self._timers: list[threading.Timer] = []
        self._reset_state()
        if state_file and state_file.is_file():
            self._load()

    # State -------------------------------------------------------------------

    def _reset_state(self) -> None:
        self.payments: dict[str, dict[str, Any]] = {}
        self.refunds: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.counter = 0

    def _load(self) -> None:
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.payments = data.get("payments", {})
        self.refunds = data.get("refunds", {})
        self.keys = {key: value for key, value in data.get("keys", {}).items() if value.get("state") != "in_progress"}
        self.events = data.get("events", [])
        self.messages = data.get("messages", [])
        self.counter = data.get("counter", 0)

    def _persist(self) -> None:
        if self.state_file:
            atomic_write_json(self.state_file, {
                "payments": self.payments, "refunds": self.refunds, "keys": self.keys,
                "events": self.events, "messages": self.messages, "counter": self.counter,
            })

    def reset(self) -> None:
        with self._lock:
            self._cancel_timers()
            self._reset_state()
            self._persist()

    def _next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}_sim_{self.counter:06d}"

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append({
            "id": self._next_id("evt"),
            "type": event_type,
            "created": int(self.clock()),
            "data": {"object": dict(payload)},
        })

    # Idempotent operations -----------------------------------------------------

    def _begin(self, scope_key: str, fingerprint: str) -> SimResponse | None:
        """Claim the key or return the response that the key already owns."""
        existing = self.keys.get(scope_key)
        if existing is None:
            self.keys[scope_key] = {"state": "in_progress", "fingerprint": fingerprint}
            return None
        if existing["fingerprint"] != fingerprint:
            return SimResponse(409, {"error": "idempotency_key_reused", "message": "same key used with a different payload"})
        if existing["state"] == "in_progress":
            return SimResponse(409, {"error": "idempotency_key_in_progress", "message": "a request with this key is still processing"})
        replay = existing["response"]
        return SimResponse(replay["status"], dict(replay["body"]), {"Idempotent-Replayed": "true"})

    def _complete(self, scope_key: str, response: SimResponse) -> SimResponse:
        self.keys[scope_key].update({"state": "completed", "response": {"status": response.status, "body": response.body}})
        self._persist()
        return response

    def _release(self, scope_key: str) -> None:
        """Forget a key whose request was never processed, so a retry is processed normally."""
        self.keys.pop(scope_key, None)
        self._persist()

    @staticmethod
    def validate_payment(payload: dict[str, Any]) -> str | None:
        """Return an error message for an invalid amount/currency/reference, or None when valid."""
        amount = payload.get("amount_minor")
        # bool is an int subclass in Python; reject it explicitly.
        if isinstance(amount, bool) or not isinstance(amount, int) or not 0 < amount <= MAX_AMOUNT_MINOR:
            return "amount_minor must be a positive integer in minor units"
        currency = payload.get("currency")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha() or not currency.isupper():
            return "currency must be an ISO 4217 code such as VND or USD"
        reference = payload.get("customer_ref", "")
        if not isinstance(reference, str) or len(reference) > 64:
            return "customer_ref must be a string of at most 64 characters"
        return None

    def create_payment(self, idempotency_key: str | None, payload: dict[str, Any], scenario: str | None = None,
                       account: str = "default") -> SimResponse:
        """Create a payment idempotently: same key + same payload replays; same key + other payload is 409."""
        scenario = scenario or payload.get("scenario") or "success"
        if scenario not in SCENARIOS:
            return SimResponse(400, {"error": "unknown_scenario", "allowed": list(SCENARIOS)})
        if not idempotency_key:
            return SimResponse(400, {"error": "idempotency_key_required"})
        validation_error = self.validate_payment(payload)
        if validation_error:
            return SimResponse(422, {"error": "invalid_request", "message": validation_error})
        scope_key = f"{account}:payments:{idempotency_key}"
        with self._lock:
            owned = self._begin(scope_key, _fingerprint(payload))
            if owned is not None:
                return owned
            if scenario == "timeout_before_processing":
                self._release(scope_key)
                return SimResponse(504, {"error": "gateway_timeout"}, delay_seconds=self.delay_seconds)
            if scenario == "server_error":
                self._release(scope_key)
                return SimResponse(500, {"error": "internal_error"})
            if scenario == "rate_limited":
                self._release(scope_key)
                return SimResponse(429, {"error": "rate_limited"}, {"Retry-After": "1"})
            if scenario != "slow_processing":
                return self._record_payment(scope_key, idempotency_key, payload, scenario, account)
        # slow_processing: the key stays in_progress while the "provider" works, so a
        # concurrent retry with the same key receives 409 instead of a second charge.
        time.sleep(self.delay_seconds)
        with self._lock:
            return self._record_payment(scope_key, idempotency_key, payload, "success", account)

    def _record_payment(self, scope_key: str, idempotency_key: str, payload: dict[str, Any], scenario: str,
                        account: str) -> SimResponse:
        status = {"decline": "failed", "pending": "pending"}.get(scenario, "succeeded")
        payment = {
            "id": self._next_id("pay"),
            "object": "payment",
            "account": account,
            "status": status,
            "amount_minor": payload["amount_minor"],
            "currency": payload["currency"],
            "customer_ref": payload.get("customer_ref"),
            "idempotency_key": idempotency_key,
            "refunded_minor": 0,
            "created": int(self.clock()),
            "livemode": False,
        }
        if scenario == "decline":
            payment["failure_code"] = "card_declined"
        self.payments[payment["id"]] = payment
        self._emit_event(f"payment.{status}", payment)
        if scenario == "decline":
            response = SimResponse(402, {"error": "card_declined", "payment": payment})
        else:
            response = SimResponse(201, payment)
        self._complete(scope_key, response)
        if scenario == "success_then_timeout":
            # The charge exists; the client only sees a gateway timeout.
            return SimResponse(504, {"error": "gateway_timeout"}, delay_seconds=self.delay_seconds)
        if scenario == "pending":
            self._schedule(self.delay_seconds, self._settle_pending, payment["id"])
        return response

    def _settle_pending(self, payment_id: str) -> None:
        with self._lock:
            payment = self.payments.get(payment_id)
            if payment and payment["status"] == "pending":
                payment["status"] = "succeeded"
                self._emit_event("payment.succeeded", payment)
                self._persist()

    def create_refund(self, idempotency_key: str | None, payload: dict[str, Any], account: str = "default") -> SimResponse:
        """Refund a succeeded payment idempotently, never above the captured amount."""
        if not idempotency_key:
            return SimResponse(400, {"error": "idempotency_key_required"})
        amount = payload.get("amount_minor")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return SimResponse(422, {"error": "invalid_request", "message": "amount_minor must be a positive integer"})
        scope_key = f"{account}:refunds:{idempotency_key}"
        with self._lock:
            owned = self._begin(scope_key, _fingerprint(payload))
            if owned is not None:
                return owned
            payment = self.payments.get(str(payload.get("payment_id")))
            if payment is None or payment["account"] != account:
                return self._complete(scope_key, SimResponse(404, {"error": "payment_not_found"}))
            if payment["status"] != "succeeded":
                return self._complete(scope_key, SimResponse(409, {"error": "payment_not_refundable", "status": payment["status"]}))
            if payment["refunded_minor"] + amount > payment["amount_minor"]:
                return self._complete(scope_key, SimResponse(409, {"error": "refund_exceeds_captured_amount"}))
            payment["refunded_minor"] += amount
            refund = {
                "id": self._next_id("ref"),
                "object": "refund",
                "payment_id": payment["id"],
                "amount_minor": amount,
                "status": "succeeded",
                "idempotency_key": idempotency_key,
                "created": int(self.clock()),
            }
            self.refunds[refund["id"]] = refund
            self._emit_event("refund.succeeded", refund)
            return self._complete(scope_key, SimResponse(201, refund))

    def get_payment(self, payment_id: str, account: str = "default") -> SimResponse:
        with self._lock:
            payment = self.payments.get(payment_id)
            if payment is None or payment["account"] != account:
                return SimResponse(404, {"error": "payment_not_found"})
            return SimResponse(200, dict(payment))

    def list_events(self) -> SimResponse:
        with self._lock:
            return SimResponse(200, {"data": list(self.events)})

    def list_messages(self) -> SimResponse:
        with self._lock:
            return SimResponse(200, {"data": list(self.messages)})

    def find_by_key(self, idempotency_key: str, account: str = "default") -> SimResponse:
        with self._lock:
            matches = [payment for payment in self.payments.values()
                       if payment["idempotency_key"] == idempotency_key and payment["account"] == account]
            return SimResponse(200, {"data": matches})

    def send_message(self, payload: dict[str, Any]) -> SimResponse:
        """Store an email/SMS/push message in the outbox; nothing is ever sent."""
        channel = payload.get("channel")
        recipient = payload.get("to")
        if channel not in ("email", "sms", "push") or not isinstance(recipient, str) or not recipient:
            return SimResponse(422, {"error": "invalid_request", "message": "channel email|sms|push and `to` are required"})
        with self._lock:
            message = {
                "id": self._next_id("msg"),
                "channel": channel,
                "to": recipient,
                "subject": payload.get("subject"),
                "body": str(payload.get("body", ""))[:2000],
                "status": "stored_in_outbox_not_sent",
                "created": int(self.clock()),
            }
            self.messages.append(message)
            self._persist()
            return SimResponse(201, message)

    # Webhooks --------------------------------------------------------------------

    def sign(self, raw_body: bytes, timestamp: int | None = None) -> str:
        timestamp = int(self.clock()) if timestamp is None else timestamp
        digest = hmac.new(self.webhook_secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={digest}"

    def deliver_webhooks(self, target_url: str, mode: str = "normal", event_ids: list[str] | None = None,
                         delay_seconds: float = 0.0) -> SimResponse:
        """POST recorded events to a loopback URL: once each, twice each (duplicate) or reversed (out_of_order)."""
        parts = urlsplit(target_url)
        if parts.scheme != "http" or (parts.hostname or "") not in LOOPBACK_HOSTS:
            # Webhooks only go to the local app under test (SAFE-004).
            return SimResponse(400, {"error": "target_must_be_loopback_http", "target_url": target_url})
        if mode not in ("normal", "duplicate", "out_of_order"):
            return SimResponse(400, {"error": "unknown_mode", "allowed": ["normal", "duplicate", "out_of_order"]})
        with self._lock:
            selected = [event for event in self.events if not event_ids or event["id"] in event_ids]
        if mode == "duplicate":
            selected = [event for event in selected for _ in range(2)]
        elif mode == "out_of_order":
            selected = list(reversed(selected))
        if delay_seconds > 0:
            self._schedule(delay_seconds, self._post_events, target_url, selected)
            return SimResponse(202, {"scheduled": len(selected), "delay_seconds": delay_seconds})
        return SimResponse(200, {"deliveries": self._post_events(target_url, selected)})

    def _post_events(self, target_url: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        for event in events:
            raw_body = json.dumps(event, separators=(",", ":")).encode()
            request = Request(target_url, data=raw_body, method="POST", headers={
                "Content-Type": "application/json",
                "Sim-Signature": self.sign(raw_body),
            })
            try:
                with urlopen(request, timeout=5) as response:
                    results.append({"event_id": event["id"], "status": response.status})
            except OSError as error:
                results.append({"event_id": event["id"], "error": str(error)[:200]})
        return results

    def _schedule(self, delay_seconds: float, function, *arguments) -> None:
        timer = threading.Timer(delay_seconds, function, arguments)
        timer.daemon = True
        self._timers = [existing for existing in self._timers if existing.is_alive()]
        self._timers.append(timer)
        timer.start()

    def _cancel_timers(self) -> None:
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()

    def shutdown(self) -> None:
        with self._lock:
            self._cancel_timers()
            self._persist()


def make_handler(simulator: PaymentSimulator, quiet: bool):
    """Build the request handler class bound to one simulator instance."""

    class SimulatorHandler(BaseHTTPRequestHandler):
        """HTTP adapter translating requests into simulator calls."""
        server_version = "devskills-payment-simulator/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            if not quiet:
                sys.stderr.write(f"[simulator] {self.address_string()} {format % args}\n")

        def _send(self, response: SimResponse) -> None:
            if response.delay_seconds:
                time.sleep(response.delay_seconds)
            body = json.dumps(response.body, ensure_ascii=False).encode()
            try:
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for name, value in response.headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # The client gave up (e.g. its own timeout); that is the scenario being simulated.
                pass

        def _read_json(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self._send(SimResponse(413, {"error": "body_too_large"}))
                return None
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send(SimResponse(400, {"error": "invalid_json"}))
                return None
            if not isinstance(data, dict):
                self._send(SimResponse(400, {"error": "json_object_required"}))
                return None
            return data

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            account = self.headers.get("X-Sim-Account", "default")
            if parts.path == "/_sim/health":
                self._send(SimResponse(200, {"status": "ok", "simulator": "payment", "livemode": False}))
            elif parts.path == "/_sim/events":
                self._send(simulator.list_events())
            elif parts.path == "/v1/messages":
                self._send(simulator.list_messages())
            elif parts.path == "/v1/payments":
                key = parse_qs(parts.query).get("idempotency_key", [""])[0]
                self._send(simulator.find_by_key(key, account))
            elif parts.path.startswith("/v1/payments/"):
                self._send(simulator.get_payment(parts.path.rsplit("/", 1)[-1], account))
            else:
                self._send(SimResponse(404, {"error": "not_found"}))

        def do_POST(self) -> None:
            parts = urlsplit(self.path)
            payload = self._read_json()
            if payload is None:
                return
            account = self.headers.get("X-Sim-Account", "default")
            key = self.headers.get("Idempotency-Key")
            if parts.path == "/v1/payments":
                self._send(simulator.create_payment(key, payload, self.headers.get("X-Sim-Scenario"), account))
            elif parts.path == "/v1/refunds":
                self._send(simulator.create_refund(key, payload, account))
            elif parts.path == "/v1/messages":
                self._send(simulator.send_message(payload))
            elif parts.path == "/_sim/webhooks/deliver":
                self._send(simulator.deliver_webhooks(str(payload.get("target_url", "")), str(payload.get("mode", "normal")),
                                                      payload.get("event_ids"), float(payload.get("delay_seconds", 0) or 0)))
            elif parts.path == "/_sim/reset":
                simulator.reset()
                self._send(SimResponse(200, {"status": "reset"}))
            else:
                self._send(SimResponse(404, {"error": "not_found"}))

    return SimulatorHandler


def start_server(simulator: PaymentSimulator, host: str = "127.0.0.1", port: int = 0, quiet: bool = True) -> ThreadingHTTPServer:
    """Create the HTTP server (not yet serving); port 0 picks a free port."""
    server = ThreadingHTTPServer((host, port), make_handler(simulator, quiet))
    server.daemon_threads = True
    return server


def cmd_simulate(args: argparse.Namespace) -> int:
    """CLI handler for `simulate payment`: serve until Ctrl-C/SIGTERM, then stop timers and persist state."""
    if args.host not in LOOPBACK_HOSTS:
        print(f"warning: binding the simulator to {args.host}; keep it on a private test network", file=sys.stderr)
    simulator = PaymentSimulator(
        webhook_secret=args.webhook_secret,
        delay_seconds=args.delay_seconds,
        state_file=Path(args.state_file) if args.state_file else None,
    )
    server = start_server(simulator, args.host, args.port, quiet=args.quiet)
    host, port = server.server_address[:2]
    print(f"payment simulator listening on http://{host}:{port}  (scenarios: {', '.join(SCENARIOS)})", flush=True)

    def stop(_signal_number: int, _frame: Any) -> None:
        # shutdown() blocks until serve_forever returns, so it must run in another thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass  # Ctrl-C is the normal way to stop the simulator; cleanup runs in finally.
    finally:
        simulator.shutdown()
        server.server_close()
    return 0
