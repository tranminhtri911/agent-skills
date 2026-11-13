"""Payment simulator: idempotency, failure scenarios, refunds, outbox, webhooks over HTTP."""

import hashlib
import hmac
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from devskills.simulators.payment import PaymentSimulator, start_server
from tests._support import make_temp_dir

BODY = {"amount_minor": 125000, "currency": "VND", "customer_ref": "cust-1"}


class SimulatorLogicTest(unittest.TestCase):
    def setUp(self):
        self.simulator = PaymentSimulator(delay_seconds=0.05)

    def test_same_key_replays_and_different_payload_conflicts(self):
        first = self.simulator.create_payment("key-1", dict(BODY))
        replay = self.simulator.create_payment("key-1", dict(BODY))
        self.assertEqual(first.status, 201)
        self.assertEqual(replay.body["id"], first.body["id"])
        self.assertEqual(replay.headers.get("Idempotent-Replayed"), "true")
        conflict = self.simulator.create_payment("key-1", BODY | {"amount_minor": 1})
        self.assertEqual((conflict.status, conflict.body["error"]), (409, "idempotency_key_reused"))
        self.assertEqual(len(self.simulator.payments), 1)

    def test_validation(self):
        self.assertEqual(self.simulator.create_payment(None, dict(BODY)).status, 400)
        for bad in ({"amount_minor": True}, {"amount_minor": 10.5}, {"amount_minor": -1}, {"currency": "vnd"}):
            self.assertEqual(self.simulator.create_payment("k", BODY | bad).status, 422, bad)

    def test_success_then_timeout_charges_once(self):
        lost = self.simulator.create_payment("key-2", dict(BODY), "success_then_timeout")
        self.assertEqual(lost.status, 504)
        retry = self.simulator.create_payment("key-2", dict(BODY))
        self.assertEqual(retry.status, 201)
        self.assertEqual(len(self.simulator.payments), 1, "the retry must not create a second charge")
        lookup = self.simulator.find_by_key("key-2")
        self.assertEqual(len(lookup.body["data"]), 1)

    def test_timeout_before_processing_releases_key(self):
        self.assertEqual(self.simulator.create_payment("key-3", dict(BODY), "timeout_before_processing").status, 504)
        self.assertEqual(len(self.simulator.payments), 0)
        self.assertEqual(self.simulator.create_payment("key-3", dict(BODY)).status, 201)

    def test_decline_rate_limit_server_error(self):
        declined = self.simulator.create_payment("key-4", dict(BODY), "decline")
        self.assertEqual((declined.status, declined.body["error"]), (402, "card_declined"))
        self.assertEqual(self.simulator.create_payment("key-4", dict(BODY)).status, 402, "a decline is replayed, not retried")
        limited = self.simulator.create_payment("key-5", dict(BODY), "rate_limited")
        self.assertEqual((limited.status, limited.headers["Retry-After"]), (429, "1"))
        self.assertEqual(self.simulator.create_payment("key-6", dict(BODY), "server_error").status, 500)
        self.assertEqual(self.simulator.create_payment("key-6", dict(BODY)).status, 201)

    def test_refunds_are_idempotent_and_bounded(self):
        payment = self.simulator.create_payment("key-7", dict(BODY)).body
        partial = self.simulator.create_refund("ref-1", {"payment_id": payment["id"], "amount_minor": 100000})
        self.assertEqual(partial.status, 201)
        self.assertEqual(self.simulator.create_refund("ref-1", {"payment_id": payment["id"], "amount_minor": 100000}).body["id"], partial.body["id"])
        too_much = self.simulator.create_refund("ref-2", {"payment_id": payment["id"], "amount_minor": 50000})
        self.assertEqual((too_much.status, too_much.body["error"]), (409, "refund_exceeds_captured_amount"))

    def test_accounts_scope_keys(self):
        first = self.simulator.create_payment("shared-key", dict(BODY), account="tenant-a")
        second = self.simulator.create_payment("shared-key", dict(BODY), account="tenant-b")
        self.assertNotEqual(first.body["id"], second.body["id"])
        self.assertEqual(self.simulator.get_payment(first.body["id"], account="tenant-b").status, 404)

    def test_outbox_and_webhook_target_restriction(self):
        message = self.simulator.send_message({"channel": "email", "to": "user@example.invalid", "body": "hi"})
        self.assertEqual(message.body["status"], "stored_in_outbox_not_sent")
        self.assertEqual(self.simulator.deliver_webhooks("https://example.com/hook").status, 400)

    def test_state_survives_restart(self):
        state_file = make_temp_dir(self) / "state.json"
        simulator = PaymentSimulator(state_file=state_file)
        created = simulator.create_payment("persisted", dict(BODY)).body
        restarted = PaymentSimulator(state_file=state_file)
        self.assertEqual(restarted.create_payment("persisted", dict(BODY)).body["id"], created["id"])


class WebhookReceiver(BaseHTTPRequestHandler):
    received: ClassVar[list] = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        WebhookReceiver.received.append((self.headers["Sim-Signature"], body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        pass


class SimulatorHttpTest(unittest.TestCase):
    def setUp(self):
        self.simulator = PaymentSimulator(webhook_secret="whsec_test", delay_seconds=0.6)
        self.server = start_server(self.simulator, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, payload, headers=None):
        request = Request(self.base + path, data=json.dumps(payload).encode(), method="POST",
                          headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def test_concurrent_retry_during_processing_gets_409(self):
        results = []
        thread = threading.Thread(target=lambda: results.append(self.post("/v1/payments", BODY | {"scenario": "slow_processing"},
                                                                          {"Idempotency-Key": "race"})))
        thread.start()
        time.sleep(0.2)
        status, body = self.post("/v1/payments", BODY | {"scenario": "slow_processing"}, {"Idempotency-Key": "race"})
        thread.join()
        self.assertEqual((status, body["error"]), (409, "idempotency_key_in_progress"))
        self.assertEqual(results[0][0], 201)
        self.assertEqual(len(self.simulator.payments), 1)

    def test_signed_webhooks_duplicate_and_out_of_order(self):
        receiver = ThreadingHTTPServer(("127.0.0.1", 0), WebhookReceiver)
        threading.Thread(target=receiver.serve_forever, daemon=True).start()
        self.addCleanup(receiver.server_close)
        self.addCleanup(receiver.shutdown)
        WebhookReceiver.received = []
        self.post("/v1/payments", BODY, {"Idempotency-Key": "w1"})
        self.post("/v1/payments", BODY | {"amount_minor": 5}, {"Idempotency-Key": "w2"})
        target = f"http://127.0.0.1:{receiver.server_address[1]}/hook"
        status, _body = self.post("/_sim/webhooks/deliver", {"target_url": target, "mode": "duplicate"})
        self.assertEqual(status, 200)
        self.assertEqual(len(WebhookReceiver.received), 4)
        signature, raw_body = WebhookReceiver.received[0]
        timestamp = signature.split(",")[0].split("=")[1]
        expected = hmac.new(b"whsec_test", f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
        self.assertEqual(signature.split("v1=")[1], expected)
        WebhookReceiver.received = []
        self.post("/_sim/webhooks/deliver", {"target_url": target, "mode": "out_of_order"})
        delivered = [json.loads(raw)["id"] for _signature, raw in WebhookReceiver.received]
        self.assertEqual(delivered, sorted(delivered, reverse=True))

    def test_lookup_and_health(self):
        self.post("/v1/payments", BODY, {"Idempotency-Key": "look"})
        with urlopen(self.base + "/v1/payments?idempotency_key=look", timeout=5) as response:
            self.assertEqual(len(json.loads(response.read())["data"]), 1)
        with urlopen(self.base + "/_sim/health", timeout=5) as response:
            self.assertFalse(json.loads(response.read())["livemode"])


if __name__ == "__main__":
    unittest.main()
