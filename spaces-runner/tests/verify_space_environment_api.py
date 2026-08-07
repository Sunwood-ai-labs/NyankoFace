"""Live, value-safe verification for the cookie-free Space environment API."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


def main() -> None:
    base_url = os.environ.get(
        "NYANKOFACE_SPACE_API_TEST_URL",
        "http://127.0.0.1:8000/api/v1/spaces/seraphim-labs/sample-gradio/environment",
    ).rstrip("/")
    token_file = Path(os.environ.get("FORGEJO_TOKEN_FILE", "/shared/token"))
    token = token_file.read_text(encoding="utf-8").strip()
    headers = {"Authorization": f"Bearer {token}"}
    secret_value = "issue-69-secret-must-never-appear"
    variable_value = "issue-69-api"
    checks: list[str] = []

    with httpx.Client(timeout=30.0) as client:
        for name, body in (
            (
                "ISSUE_69_SECRET",
                {"kind": "secret", "value": secret_value, "enabled": True},
            ),
            (
                "ISSUE_69_MODE",
                {"kind": "variable", "value": variable_value, "enabled": True},
            ),
        ):
            response = client.put(f"{base_url}/{name}", headers=headers, json=body)
            response.raise_for_status()
            assert secret_value not in response.text
            assert variable_value not in response.text
            assert "value" not in response.json()["item"]
            checks.append(f"upsert:{name}:200:redacted")

        response = client.get(base_url, headers=headers)
        response.raise_for_status()
        assert secret_value not in response.text
        assert variable_value not in response.text
        items = {item["name"]: item for item in response.json()["items"]}
        assert items["ISSUE_69_SECRET"]["kind"] == "secret"
        assert items["ISSUE_69_MODE"]["kind"] == "variable"
        checks.append("list:200:metadata-only")

        response = client.patch(
            f"{base_url}/ISSUE_69_SECRET",
            headers=headers,
            json={"enabled": False},
        )
        response.raise_for_status()
        assert response.json()["item"]["enabled"] is False
        checks.append("disable:200")

        response = client.get(f"{base_url}/audit", headers=headers)
        response.raise_for_status()
        assert secret_value not in response.text
        assert variable_value not in response.text
        actions = {
            item["action"]
            for item in response.json()["items"]
            if item["name"].startswith("ISSUE_69_")
        }
        assert {"create", "disable"} <= actions
        checks.append("audit:200:value-free")

        for name in ("ISSUE_69_SECRET", "ISSUE_69_MODE"):
            first = client.delete(f"{base_url}/{name}", headers=headers)
            second = client.delete(f"{base_url}/{name}", headers=headers)
            first.raise_for_status()
            second.raise_for_status()
            assert second.json()["deleted"] is False
        checks.append("delete:200:idempotent")

    print(json.dumps({"passed": True, "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
