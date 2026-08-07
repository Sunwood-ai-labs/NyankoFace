import unittest

from pages_metadata import complete_pages_metadata


def render(source: str, path: str = "https://hub.example/pages/acme/hello/") -> str:
    return complete_pages_metadata(
        source.encode(),
        repo_name="hello-world",
        description="A friendly sample",
        page_url=path,
    ).decode()


class PagesMetadataTests(unittest.TestCase):
    def test_adds_fallback_title_and_social_metadata(self):
        result = render("<html><head></head><body>Hello</body></html>")
        self.assertIn("<title>Hello World</title>", result)
        self.assertIn('property="og:title" content="Hello World"', result)
        self.assertIn('property="og:site_name" content="Hello World"', result)
        self.assertIn('name="twitter:title" content="Hello World"', result)
        self.assertIn(
            'property="og:url" content="https://hub.example/pages/acme/hello/"',
            result,
        )

    def test_preserves_explicit_metadata_and_normalizes_relative_image(self):
        source = """<html><head>
          <title>Author title</title>
          <meta content="Author social title" property="og:title">
          <meta property="og:site_name" content="Author site">
          <meta content="../cover.png" property="og:image">
          <meta name="twitter:title" content="Author tweet">
        </head><body></body></html>"""
        result = render(source, "https://hub.example/pages/acme/hello/guides/start.html")
        self.assertEqual(result.count("<title>"), 1)
        self.assertEqual(result.count('property="og:title"'), 1)
        self.assertIn('content="Author social title"', result)
        self.assertIn('content="Author site"', result)
        self.assertIn('content="Author tweet"', result)
        self.assertIn(
            'content="https://hub.example/pages/acme/hello/cover.png"',
            result,
        )

    def test_does_not_touch_non_utf8_content(self):
        content = b"\xff\xd8\xff"
        self.assertEqual(
            complete_pages_metadata(
                content,
                repo_name="image",
                description=None,
                page_url="https://hub.example/image",
            ),
            content,
        )


if __name__ == "__main__":
    unittest.main()
