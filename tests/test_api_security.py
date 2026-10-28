import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from mathernet.api import create_server, is_allowed_host, is_allowed_origin
from mathernet.deep_dive_sessions import DeepDiveSessionStore
from mathernet.formula_introductions import FormulaIntroductionStore
from mathernet.gateway import GatewayStore
from mathernet.map_sessions import MapSessionStore
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService


class ApiSecurityHelpersTests(unittest.TestCase):
    def test_host_allowlist(self):
        self.assertTrue(is_allowed_host("127.0.0.1:8765", 8765))
        self.assertTrue(is_allowed_host("localhost:8765", 8765))
        self.assertTrue(is_allowed_host("[::1]:8765", 8765))
        self.assertTrue(is_allowed_host("127.0.0.1", 8765))
        self.assertFalse(is_allowed_host("evil.example:8765", 8765))
        self.assertFalse(is_allowed_host("127.0.0.1:9999", 8765))
        self.assertFalse(is_allowed_host("127.0.0.1.evil.example:8765", 8765))
        self.assertFalse(is_allowed_host("", 8765))

    def test_origin_allowlist(self):
        self.assertTrue(is_allowed_origin("http://127.0.0.1:8765", 8765))
        self.assertTrue(is_allowed_origin("http://localhost:8765", 8765))
        self.assertFalse(is_allowed_origin("https://127.0.0.1:8765", 8765))
        self.assertFalse(is_allowed_origin("http://evil.example:8765", 8765))
        self.assertFalse(is_allowed_origin("http://127.0.0.1:9999", 8765))
        self.assertFalse(is_allowed_origin("null", 8765))
        self.assertFalse(is_allowed_origin("http://[::1", 8765))


class ApiSecurityServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.service = MathernetService(
            GraphRepository(root / "graph.json"),
            gateway_store=GatewayStore(root / "gateway.json"),
            deep_dive_sessions=DeepDiveSessionStore(root / "deep_dive_sessions.json"),
            formula_introductions=FormulaIntroductionStore(root / "introductions.json"),
            map_sessions=MapSessionStore(root / "map_sessions.json"),
        )
        self.server = create_server(self.service, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, method, path, *, headers=None, body=None):
        headers = dict(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.putrequest(method, path, skip_host=True)
            connection.putheader(
                "Host", headers.pop("Host", f"127.0.0.1:{self.port}")
            )
            for name, value in headers.items():
                connection.putheader(name, value)
            payload = None if body is None else body.encode("utf-8")
            if payload is not None:
                connection.putheader("Content-Length", str(len(payload)))
            connection.endheaders()
            if payload is not None:
                connection.send(payload)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_untrusted_host_is_rejected(self):
        status, headers, body = self.request(
            "GET", "/api/health", headers={"Host": "evil.example"}
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "forbidden")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_cross_origin_mutation_is_rejected(self):
        status, _, _ = self.request(
            "POST",
            "/api/map-sessions",
            headers={
                "Content-Type": "application/json",
                "Origin": "https://evil.example",
            },
            body=json.dumps({"name": "Injected map"}),
        )
        self.assertEqual(status, 403)
        names = [session["name"] for session in self.service.list_map_sessions()["sessions"]]
        self.assertNotIn("Injected map", names)

    def test_same_origin_request_is_allowed_without_cors_header(self):
        status, headers, body = self.request(
            "GET",
            "/api/health",
            headers={"Origin": f"http://127.0.0.1:{self.port}"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_foreign_preflight_is_rejected(self):
        status, _, _ = self.request(
            "OPTIONS",
            "/api/gateway",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
