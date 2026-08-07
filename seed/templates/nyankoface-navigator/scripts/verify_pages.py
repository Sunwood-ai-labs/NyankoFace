#!/usr/bin/env python3
"""Live-check an NyankoFace Pages root plus optional assets and nested routes."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


@dataclass
class Check:
    kind: str
    url: str
    ok: bool
    status: int
    content_type: str
    error: str = ""


def pages_root(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Pages URL must be an absolute HTTP or HTTPS URL")
    path = parsed.path if parsed.path.endswith("/") else f"{parsed.path}/"
    return parsed._replace(path=path, params="", query="", fragment="").geturl()


def check(kind: str, url: str, timeout: float) -> Check:
    request = Request(url, headers={"User-Agent": "NyankoFace-Navigator/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            content_type = response.headers.get("content-type", "")
            response.read(1)
        return Check(kind, url, 200 <= status < 400, status, content_type)
    except HTTPError as exc:
        return Check(kind, url, False, int(exc.code), exc.headers.get("content-type", ""), str(exc))
    except URLError as exc:
        return Check(kind, url, False, 0, "", str(exc.reason))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Pages root URL")
    parser.add_argument("--asset", action="append", default=[], help="relative asset path")
    parser.add_argument("--nested", action="append", default=[], help="relative nested page")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        root = pages_root(args.url)
    except ValueError as exc:
        parser.error(str(exc))

    targets = [("root", root)]
    targets.extend(("asset", urljoin(root, path)) for path in args.asset)
    targets.extend(("nested", urljoin(root, path)) for path in args.nested)
    results = [check(kind, url, args.timeout) for kind, url in targets]

    if args.as_json:
        print(json.dumps({"root": root, "checks": [asdict(item) for item in results]}, indent=2))
    else:
        for item in results:
            marker = "PASS" if item.ok else "FAIL"
            detail = f"{item.status} {item.content_type}".strip()
            if item.error:
                detail = f"{detail} {item.error}".strip()
            print(f"{marker:4} {item.kind:6} {item.url} {detail}")

    return 0 if all(item.ok for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
