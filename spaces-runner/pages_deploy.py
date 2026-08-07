"""Repository-backed NyankoFace Pages deployment helpers."""
from __future__ import annotations

from typing import Any, Literal

import httpx
import config
import forgejo

PagesMethod = Literal["gh-pages", "docs", "vitepress"]


class PagesOutcomeUnknown(forgejo.ForgejoError):
    """A Pages write may have reached Forgejo before its response failed."""


async def _write_outcome(awaitable, *, prior_write: bool = False):
    try:
        return await awaitable
    except forgejo.ForgejoOutcomeUnknown as exc:
        raise PagesOutcomeUnknown(str(exc)) from exc
    except forgejo.ForgejoPreflightError as exc:
        if not prior_write:
            raise
        raise PagesOutcomeUnknown(str(exc)) from exc
    except forgejo.ForgejoWriteRejected as exc:
        if not prior_write:
            raise
        raise PagesOutcomeUnknown(str(exc)) from exc
    except (ValueError, AttributeError, TypeError) as exc:
        if not prior_write:
            raise
        raise PagesOutcomeUnknown("Pages verification returned invalid data") from exc
    except (forgejo.ForgejoError, httpx.HTTPError) as exc:
        if not prior_write:
            raise
        raise PagesOutcomeUnknown(str(exc)) from exc

STATIC_INDEX = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>NyankoFace Pages</title>
    <meta name="description" content="A static site published with NyankoFace Pages">
  </head>
  <body>
    <main>
      <h1>NyankoFace Pages</h1>
      <p>Edit this page in Forgejo and publish every update from Git.</p>
    </main>
  </body>
</html>
"""

VITEPRESS_PACKAGE = """{
  "name": "nyankoface-pages",
  "private": true,
  "scripts": {
    "docs:build": "vitepress build docs"
  },
  "devDependencies": {
    "vitepress": "1.6.3"
  }
}
"""

VITEPRESS_INDEX = """---
layout: home

hero:
  name: NyankoFace Pages
  text: VitePress, published automatically
  tagline: Push documentation to main and Forgejo Actions publishes it.
---
"""

VITEPRESS_CONFIG = """import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'NyankoFace Pages',
  description: 'VitePress documentation published by Forgejo Actions',
  base: process.env.VITEPRESS_BASE ?? '/',
})
"""

VITEPRESS_WORKFLOW = """name: Publish VitePress to NyankoFace Pages

on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - 'package.json'
      - 'package-lock.json'
      - '.forgejo/workflows/publish-pages.yml'
  workflow_dispatch:

jobs:
  publish:
    runs-on: node20
    steps:
      - name: Check out the source
        uses: https://data.forgejo.org/actions/checkout@v4
      - name: Install dependencies
        run: npm install --no-audit --no-fund
      - name: Build VitePress
        run: VITEPRESS_BASE="/pages/${GITHUB_REPOSITORY}/" npm run docs:build
      - name: Publish the static site
        env:
          PAGES_TOKEN: ${{ github.token }}
        run: |
          git config user.name "NyankoFace Pages"
          git config user.email "pages@nyankoface.local"
          git checkout --orphan gh-pages
          git rm -rf .
          cp -R docs/.vitepress/dist/. .
          touch .nojekyll
          git add --all
          git commit -m "Publish Pages for ${GITHUB_SHA}"
          git remote set-url origin "http://oauth2:${PAGES_TOKEN}@forgejo:3000/${GITHUB_REPOSITORY}.git"
          git push --force origin gh-pages
"""


def deployment_plan(method: PagesMethod, default_branch: str) -> list[dict[str, str]]:
    if method == "gh-pages":
        return [{"branch": "gh-pages", "path": "index.html"}]
    if method == "docs":
        return [{"branch": default_branch, "path": "docs/index.html"}]
    return [
        {"branch": default_branch, "path": "package.json"},
        {"branch": default_branch, "path": "docs/index.md"},
        {"branch": default_branch, "path": "docs/.vitepress/config.mts"},
        {
            "branch": default_branch,
            "path": ".forgejo/workflows/publish-pages.yml",
        },
    ]


async def deploy(
    owner: str,
    repo: str,
    method: PagesMethod,
    token: str | None,
    actor: str,
) -> dict:
    repo_info = await forgejo.get_repo_info(owner, repo, token)
    if repo_info.get("private"):
        raise forgejo.ForgejoError(
            "NyankoFace Pages only publishes public repositories."
        )
    default_branch = repo_info.get("default_branch") or "main"
    plan = deployment_plan(method, default_branch)
    logs = [
        f"Verified public repository {owner}/{repo}.",
        f"Selected {method} publishing method.",
    ]
    commits: list[dict[str, Any]] = []
    write_started = False

    if method == "gh-pages":
        created = await _write_outcome(forgejo.ensure_branch(
            owner, repo, "gh-pages", default_branch, token
        ))
        write_started = created
        logs.append(
            "Created gh-pages from the default branch."
            if created
            else "Reused the existing gh-pages branch."
        )
        commit = await _write_outcome(forgejo.upsert_repo_file(
            owner,
            repo,
            "gh-pages",
            "index.html",
            STATIC_INDEX,
            "pages: publish static starter",
            token,
            actor,
        ), prior_write=write_started)
        write_started = write_started or commit["changed"]
        commits.append(commit)
        logs.append("Published gh-pages/index.html.")
    elif method == "docs":
        commit = await _write_outcome(forgejo.upsert_repo_file(
            owner,
            repo,
            default_branch,
            "docs/index.html",
            STATIC_INDEX,
            "pages: publish docs starter",
            token,
            actor,
        ), prior_write=write_started)
        write_started = write_started or commit["changed"]
        commits.append(commit)
        logs.append(f"Published {default_branch}/docs/index.html.")
    else:
        workflow = VITEPRESS_WORKFLOW.replace(
            "branches: [main]",
            f"branches: [{default_branch}]",
        )
        files = [
            ("package.json", VITEPRESS_PACKAGE),
            ("docs/index.md", VITEPRESS_INDEX),
            ("docs/.vitepress/config.mts", VITEPRESS_CONFIG),
            (".forgejo/workflows/publish-pages.yml", workflow),
        ]
        for path, content in files:
            commit = await _write_outcome(forgejo.upsert_repo_file(
                owner,
                repo,
                default_branch,
                path,
                content,
                f"pages: add {path}",
                token,
                actor,
            ), prior_write=write_started)
            write_started = write_started or commit["changed"]
            commits.append(commit)
            logs.append(f"Added {default_branch}/{path}.")
        logs.append(
            "Forgejo Actions will build the project and publish gh-pages."
        )

    public_url = (
        f"{config.PUBLIC_BASE_URL.rstrip('/')}/pages/{owner}/{repo}/"
    )
    inspection = await _write_outcome(
        forgejo.inspect_pages_source(owner, repo, token), prior_write=write_started,
    )
    status = (
        "published"
        if inspection["status"] == "published"
        else "queued"
        if method == "vitepress"
        else "failed"
    )
    if status == "published":
        logs.append(f"Verified published URL {public_url}.")
    elif method == "vitepress":
        logs.append("Waiting for the Forgejo Actions deployment.")
    else:
        logs.extend(inspection.get("reasons") or ["Pages verification failed."])

    return {
        "owner": owner,
        "repo": repo,
        "method": method,
        "status": status,
        "public_url": public_url,
        "actions_url": f"/git/{owner}/{repo}/actions",
        "plan": plan,
        "commits": commits,
        "logs": logs,
        "inspection": inspection,
    }
