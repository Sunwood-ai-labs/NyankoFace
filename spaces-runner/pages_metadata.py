"""Non-destructive social metadata completion for NyankoFace Pages HTML."""
from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlparse


_META_TEMPLATE = '<meta {attribute}="{key}" content="{value}" />'


def humanize_repo_name(name: str) -> str:
    words = re.sub(r"[-_]+", " ", name).strip().split()
    return " ".join(word[:1].upper() + word[1:] for word in words) or "NyankoFace Pages"


def _content_for(document: str, attribute: str, key: str) -> str | None:
    for match in re.finditer(r"<meta\b[^>]*>", document, re.IGNORECASE | re.DOTALL):
        attributes = {
            name.lower(): value
            for name, _, value in re.findall(
                r"""([\w:-]+)\s*=\s*(["'])(.*?)\2""",
                match.group(0),
                re.DOTALL,
            )
        }
        if attributes.get(attribute) == key and "content" in attributes:
            return html.unescape(attributes["content"].strip())
    return None


def _title_for(document: str) -> str | None:
    match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", document, re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return html.unescape(re.sub(r"\s+", " ", match.group(1)).strip())


def _absolute_image_urls(document: str, page_url: str) -> str:
    def replace_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        attributes = {
            name.lower(): value
            for name, _, value in re.findall(
                r"""([\w:-]+)\s*=\s*(["'])(.*?)\2""",
                tag,
                re.DOTALL,
            )
        }
        is_image = (
            attributes.get("property") == "og:image"
            or attributes.get("name") == "twitter:image"
        )
        value = html.unescape(attributes.get("content", "").strip())
        parsed = urlparse(value)
        if (
            not is_image
            or not value
            or parsed.scheme
            or value.startswith(("//", "data:", "#"))
        ):
            return tag
        absolute = html.escape(urljoin(page_url, value), quote=True)
        return re.sub(
            r"""(\bcontent\s*=\s*)(["'])(.*?)\2""",
            lambda content_match: (
                f"{content_match.group(1)}{content_match.group(2)}"
                f"{absolute}{content_match.group(2)}"
            ),
            tag,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )

    return re.sub(r"<meta\b[^>]*>", replace_tag, document, flags=re.IGNORECASE | re.DOTALL)


def complete_pages_metadata(
    content: bytes,
    *,
    repo_name: str,
    description: str | None,
    page_url: str,
) -> bytes:
    """Add missing sharing metadata while preserving repository-authored values."""
    try:
        document = content.decode("utf-8")
    except UnicodeDecodeError:
        return content

    title = (
        _title_for(document)
        or _content_for(document, "property", "og:title")
        or _content_for(document, "name", "twitter:title")
        or humanize_repo_name(repo_name)
    )
    escaped_title = html.escape(title, quote=True)
    additions: list[str] = []

    if not _title_for(document):
        additions.append(f"<title>{html.escape(title)}</title>")
    if not _content_for(document, "property", "og:title"):
        additions.append(_META_TEMPLATE.format(attribute="property", key="og:title", value=escaped_title))
    if not _content_for(document, "property", "og:site_name"):
        additions.append(_META_TEMPLATE.format(attribute="property", key="og:site_name", value=escaped_title))
    if not _content_for(document, "property", "og:type"):
        additions.append(_META_TEMPLATE.format(attribute="property", key="og:type", value="website"))
    if not _content_for(document, "property", "og:url"):
        additions.append(
            _META_TEMPLATE.format(
                attribute="property", key="og:url", value=html.escape(page_url, quote=True)
            )
        )
    if description and not _content_for(document, "property", "og:description"):
        additions.append(
            _META_TEMPLATE.format(
                attribute="property",
                key="og:description",
                value=html.escape(description.strip(), quote=True),
            )
        )
    if not _content_for(document, "name", "twitter:card"):
        additions.append(_META_TEMPLATE.format(attribute="name", key="twitter:card", value="summary"))
    if not _content_for(document, "name", "twitter:title"):
        additions.append(_META_TEMPLATE.format(attribute="name", key="twitter:title", value=escaped_title))

    metadata = "\n    ".join(additions)
    if metadata:
        if re.search(r"</head\s*>", document, re.IGNORECASE):
            document = re.sub(
                r"</head\s*>",
                f"    {metadata}\n  </head>",
                document,
                count=1,
                flags=re.IGNORECASE,
            )
        elif re.search(r"<html\b[^>]*>", document, re.IGNORECASE):
            document = re.sub(
                r"(<html\b[^>]*>)",
                rf"\1\n  <head>\n    {metadata}\n  </head>",
                document,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            document = f"<head>\n    {metadata}\n</head>\n{document}"

    return _absolute_image_urls(document, page_url).encode("utf-8")
