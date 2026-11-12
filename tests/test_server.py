"""Only the page this app opened can use it: other Host or Origin names are turned away."""
import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer

from couchtv_setup import server


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path, host=None, origin=None, key=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if origin:
            headers["Origin"] = origin
        if key:
            headers["X-Setup-Key"] = server.SECRET
        c.request("GET", path, headers=headers)
        r = c.getresponse()
        r.read()
        return r

    def test_page_and_api_work(self):
        r = self.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertEqual(self.get("/api/ping").status, 200)
        self.assertEqual(self.get("/api/ping", origin=f"http://127.0.0.1:{self.port}").status, 200)

    def test_other_host_names_are_refused(self):
        # a website that points its own name at 127.0.0.1
        self.assertEqual(self.get("/", host=f"evil.example:{self.port}").status, 403)
        self.assertEqual(self.get("/api/ping", host=f"evil.example:{self.port}").status, 403)

    def test_other_origins_are_refused(self):
        self.assertEqual(self.get("/api/ping", origin="https://evil.example").status, 403)

    def test_no_key_is_refused(self):
        self.assertEqual(self.get("/api/ping", key=False).status, 403)


if __name__ == "__main__":
    unittest.main()
