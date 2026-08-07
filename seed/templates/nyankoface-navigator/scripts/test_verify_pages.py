import io
import importlib.util
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("verify_pages.py")
SPEC = importlib.util.spec_from_file_location("verify_pages", SCRIPT)
assert SPEC and SPEC.loader
verify_pages = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_pages
SPEC.loader.exec_module(verify_pages)


class FakeResponse:
    status = 200

    def __init__(self, content_type: str = "text/html") -> None:
        self.headers = Message()
        self.headers["content-type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size: int) -> bytes:
        return b"<"


class PagesVerificationTests(unittest.TestCase):
    def test_normalizes_absolute_root(self) -> None:
        self.assertEqual(
            verify_pages.pages_root("https://hub.example/pages/acme/site?x=1#top"),
            "https://hub.example/pages/acme/site/",
        )

    def test_rejects_relative_or_non_http_url(self) -> None:
        for value in ("/pages/acme/site/", "file:///tmp/index.html"):
            with self.assertRaises(ValueError):
                verify_pages.pages_root(value)

    @patch("verify_pages.urlopen", return_value=FakeResponse())
    def test_checks_root_assets_and_nested_pages(self, mocked) -> None:
        with patch("sys.stdout", new=io.StringIO()):
            result = verify_pages.main([
                "https://hub.example/pages/acme/site/",
                "--asset",
                "assets/app.css",
                "--nested",
                "guide/",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(mocked.call_count, 3)


if __name__ == "__main__":
    unittest.main()
