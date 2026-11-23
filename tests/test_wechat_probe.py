"""Offline unit tests; no external network, tokens or live WeChat access."""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("wechat_probe", ROOT / "scripts" / "wechat_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
pub_spec = importlib.util.spec_from_file_location("publish_draft", ROOT / "scripts" / "publish_draft.py")
publisher = importlib.util.module_from_spec(pub_spec)
pub_spec.loader.exec_module(publisher)


class Response:
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class WeChatProbeTests(unittest.TestCase):
    def test_token_and_readonly_count(self):
        requests = []
        def fake_urlopen(request, timeout):
            requests.append(request)
            if request.get_method() == "POST":
                payload = json.loads(request.data)
                self.assertFalse(payload["force_refresh"])
                self.assertEqual(payload["secret"], "test-secret-not-real")
                return Response({"access_token": "fake-token", "expires_in": 7200})
            self.assertIn("/cgi-bin/draft/count", request.full_url)
            return Response({"errcode": 0, "total_count": 3})
        with mock.patch.object(probe.urllib.request, "urlopen", side_effect=fake_urlopen):
            result = probe.run_check({"WECHAT_APP_ID": "test-app", "WECHAT_APP_SECRET": "test-secret-not-real"})
        self.assertEqual(result["total_count"], 3)
        self.assertEqual(len(requests), 2)
        self.assertEqual(result["draft_add"], "not_tested")
        self.assertEqual(result["public_publish"], "disabled")

    def test_unauthorized_48001(self):
        with mock.patch.object(probe.urllib.request, "urlopen",
                               return_value=Response({"errcode": 48001, "errmsg": "api unauthorized"})):
            with self.assertRaises(probe.ProbeError) as e:
                probe.stable_token("fake", "fake")
        self.assertEqual(e.exception.code, 48001)

    def test_ip_white_list_40164(self):
        with mock.patch.object(probe.urllib.request, "urlopen",
                               return_value=Response({"errcode": 40164, "errmsg": "invalid ip fake-secret"})):
            with self.assertRaises(probe.ProbeError) as e:
                probe.stable_token("fake", "fake")
        self.assertEqual(e.exception.code, 40164)

    def test_missing_credentials(self):
        with self.assertRaises(probe.ProbeError) as e:
            probe.run_check({})
        self.assertEqual(e.exception.code, "credentials_missing")

    def test_token_missing(self):
        with mock.patch.object(probe.urllib.request, "urlopen", return_value=Response({"expires_in": 7200})):
            with self.assertRaises(probe.ProbeError):
                probe.stable_token("fake", "fake")

    def test_draft_count_missing(self):
        with mock.patch.object(probe.urllib.request, "urlopen", return_value=Response({"errcode": 0})):
            with self.assertRaises(probe.ProbeError):
                probe.draft_count("fake")

    def test_no_write_routes(self):
        for path in ("/cgi-bin/draft/add", "/cgi-bin/freepublish/submit",
                     "/cgi-bin/message/mass/sendall"):
            with self.assertRaises(probe.ProbeError) as e:
                probe._request_json("POST", path, payload={})
            self.assertEqual(e.exception.code, "route_not_allowed")

    def test_network_error_does_not_leak_token(self):
        def fail(*args, **kwargs):
            raise probe.urllib.error.URLError("access_token=very-secret-token")
        with mock.patch.object(probe.urllib.request, "urlopen", side_effect=fail):
            with self.assertRaises(probe.ProbeError) as e:
                probe.draft_count("very-secret-token")
        self.assertNotIn("very-secret-token", str(e.exception))

    def test_error_message_not_echoed(self):
        with mock.patch.object(probe.urllib.request, "urlopen", return_value=Response({
            "errcode": 40164, "errmsg": "invalid ip / secret in error"
        })):
            buf = io.StringIO()
            with mock.patch.dict(os.environ, {"WECHAT_APP_ID": "fake", "WECHAT_APP_SECRET": "fake"}):
                with contextlib.redirect_stdout(buf):
                    result = probe.main(["--check"])
            self.assertEqual(result, 1)
            self.assertNotIn("secret in error", buf.getvalue())
            self.assertIn("40164", buf.getvalue())

    def test_publisher_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            html = Path(d) / "draft.html"
            cover = Path(d) / "cover.jpg"
            html.write_text("<section>test</section>", encoding="utf-8")
            cover.write_bytes(b"fake-cover")
            args = ["publish_draft.py", str(html), "--title", "测试", "--cover", str(cover)]
            with mock.patch.object(publisher.sys, "argv", args), mock.patch.object(
                publisher, "get_token", side_effect=AssertionError("network must not be called")
            ):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as e:
                        publisher.main()
            self.assertEqual(e.exception.code, 2)

    def test_publisher_rejects_old_secret_flags(self):
        with mock.patch.object(publisher.sys, "argv",
                               ["publish_draft.py", "missing.html", "--title", "test", "--app-secret", "fake"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as e:
                    publisher.main()
        self.assertEqual(e.exception.code, 2)

    def test_publisher_secret_only_from_env(self):
        with mock.patch.dict(os.environ, {
            "WECHAT_APP_ID": "test-app", "WECHAT_APP_SECRET": "test-secret"
        }):
            self.assertEqual(publisher.load_credentials(), ("test-app", "test-secret"))


if __name__ == "__main__":
    unittest.main()
