"""Seed deterministic demo activity by calling the public agent API itself."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

import config


def stable_number(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def main() -> None:
    credentials = json.loads(Path(config.AGENT_CREDENTIALS_FILE).read_text(encoding="utf-8"))
    forgejo_headers = {}
    token = config.read_forgejo_token()
    if token:
        forgejo_headers["Authorization"] = f"token {token}"

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{config.FORGEJO_API}/repos/search",
            params={"q": "space", "topic": "true", "limit": 50},
            headers=forgejo_headers,
        )
        response.raise_for_status()
        repos = response.json().get("data", [])

        view_calls = 0
        like_calls = 0
        for slug, api_key in credentials.items():
            headers = {"Authorization": f"Bearer {api_key}"}
            for repo in repos:
                owner = repo["owner"]["login"]
                name = repo["name"]
                score = stable_number(f"{slug}:{owner}/{name}")
                view_count = 2 + score % 5
                for index in range(view_count):
                    result = client.post(
                        f"http://localhost:8000/api/agent/v1/repos/{owner}/{name}/views",
                        headers={**headers, "Idempotency-Key": f"demo-v1:{slug}:{owner}:{name}:{index}"},
                    )
                    result.raise_for_status()
                    view_calls += 1
                if score % 4 != 0:
                    result = client.put(
                        f"http://localhost:8000/api/agent/v1/repos/{owner}/{name}/like",
                        headers=headers,
                    )
                    result.raise_for_status()
                    like_calls += 1

    print(f"Seeded {len(credentials)} agents across {len(repos)} Spaces: {view_calls} view calls, {like_calls} like calls")


if __name__ == "__main__":
    main()
