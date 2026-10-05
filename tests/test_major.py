import http.server
import sys
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from fawlty import common  # noqa: E402
from fawlty.guests import major  # noqa: E402


class _Redirector(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        port = self.server.server_address[1]
        targets = {
            "/to-allowed": f"http://127.0.0.1:{port}/ok",
            "/to-other-host": f"http://localhost:{port}/ok",
            "/to-file": "file:///etc/passwd",
        }
        if self.path in targets:
            self.send_response(302)
            self.send_header("Location", targets[self.path])
            self.end_headers()
            return
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class MajorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Redirector)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.allow = mock.patch.object(major, "_ALLOWED_HOSTS", frozenset({"127.0.0.1"}))
        cls.allow.start()

    @classmethod
    def tearDownClass(cls):
        cls.allow.stop()
        cls.server.shutdown()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_follows_redirect_within_allowlist(self):
        self.assertEqual(major._fetch(self.url("/to-allowed"))[0], 200)

    def test_refuses_redirect_to_other_host(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            major._fetch(self.url("/to-other-host"))
        self.assertIn("non-allowlisted", str(cm.exception))

    def test_refuses_redirect_to_other_scheme(self):
        with self.assertRaises(urllib.error.HTTPError):
            major._fetch(self.url("/to-file"))

    def test_refuses_non_allowlisted_url(self):
        with self.assertRaises(ValueError):
            major._fetch("http://localhost/")

    def test_real_allowlist_hosts(self):
        hosts = {h for h in (major.urlsplit(u).hostname for u in common.SAFE_SITES)}
        self.assertNotIn(None, hosts)
        self.assertTrue(all(u.startswith(("http://", "https://")) for u in common.SAFE_SITES))


if __name__ == "__main__":
    unittest.main()
