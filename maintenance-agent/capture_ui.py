from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture real UI evidence for an NyankoFace maintenance job")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--selector", default="")
    parser.add_argument("--full-page", action="store_true")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--fail-on-errors", action="store_true")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=args.chromium,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(
            viewport={"width": args.width, "height": args.height},
            ignore_https_errors=True,
        )
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "response",
            lambda response: failed_requests.append(f"{response.status} {response.url}")
            if response.status >= 400
            else None,
        )
        page.goto(args.url, wait_until="networkidle", timeout=args.timeout_ms)
        if args.selector:
            page.locator(args.selector).wait_for(state="visible", timeout=args.timeout_ms)
        page.screenshot(path=str(output), full_page=args.full_page)
        metrics = page.evaluate(
            """() => ({
                title: document.title,
                clientWidth: document.documentElement.clientWidth,
                scrollWidth: document.documentElement.scrollWidth,
                bodyScrollWidth: document.body?.scrollWidth ?? 0,
                activeElement: document.activeElement?.tagName ?? null
            })"""
        )
        browser.close()

    result = {
        "url": args.url,
        "output": str(output),
        "viewport": f"{args.width}x{args.height}",
        "title": metrics["title"],
        "horizontalOverflow": max(0, metrics["scrollWidth"] - metrics["clientWidth"]),
        "bodyHorizontalOverflow": max(0, metrics["bodyScrollWidth"] - metrics["clientWidth"]),
        "consoleErrors": console_errors,
        "pageErrors": page_errors,
        "failedRequests": failed_requests,
    }
    print(json.dumps(result, ensure_ascii=False))
    has_errors = (
        result["horizontalOverflow"] > 0
        or result["bodyHorizontalOverflow"] > 0
        or bool(console_errors)
        or bool(page_errors)
        or bool(failed_requests)
    )
    return 2 if args.fail_on_errors and has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
