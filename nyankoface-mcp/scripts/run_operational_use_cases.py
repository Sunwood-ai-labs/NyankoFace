"""Run agent-facing operational MCP use cases against a live endpoint."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from run_live_client_protocol import (
    EXPECTED_PROTOCOL_VERSION,
    notify_initialized,
    require_advertised_item,
    require_auth_rejection,
    require_content_blocks,
    require_error_flag,
    require_initialize_result,
    require_list_result,
    require_openapi_resource,
    require_resource_items,
    require_result,
    require_secure_endpoint,
    require_tool_items,
    rpc,
)


REQUIRED_OPERATIONAL_TOOLS = (
    "search_catalog",
    "list_repositories",
    "get_repository",
    "get_tree",
    "get_file",
    "get_knowledge",
    "list_issues",
    "get_issue",
    "create_issue",
)
ARTICLE_PATH_PATTERN = re.compile(
    r"""(?:^|[/\\("' ])articles/([A-Za-z0-9][A-Za-z0-9._-]*)(?:\.md)?"""
)
MAX_CATALOG_PAGES = 20


def _catalog_candidate_error_is_skippable(message: str) -> bool:
    lowered = message.casefold()
    if "invalid_upstream_response" in lowered:
        return False
    if any(
        marker in lowered
        for marker in (
            "upstream_unavailable",
            "temporarily unavailable",
            "rate_limited",
            "rate limit",
            "http 5",
        )
    ):
        return False
    return any(
        marker in lowered
        for marker in (
            "not_found_or_unauthorized",
            "catalog item is missing",
            "has no articles/ directory",
            "has no markdown article",
            "no published knowledge article slug",
            "knowledge article identity mismatch",
        )
    )


def _catalog_candidate_skip_reason(message: str) -> str:
    lowered = message.casefold()
    if "not_found_or_unauthorized" in lowered:
        return "not_found_or_unauthorized"
    if "has no articles/ directory" in lowered:
        return "missing_articles_directory"
    if "articles/ returned no entries" in lowered:
        return "empty_articles_directory"
    if "has no markdown article" in lowered:
        return "no_markdown_article"
    if "no published knowledge article slug" in lowered:
        return "knowledge_not_published"
    if "knowledge article identity mismatch" in lowered:
        return "knowledge_repository_mismatch"
    if "catalog item is missing" in lowered:
        return "invalid_catalog_identity"
    return "invalid_catalog_candidate"


def _content_text(result: dict[str, Any]) -> str:
    return "\n".join(
        str(item.get("text", ""))
        for item in result.get("content", [])
        if isinstance(item, dict) and item.get("type") == "text"
    ).strip()


def _structured_payload(result: dict[str, Any], tool: str) -> dict[str, Any]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in result.get("content", []):
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        try:
            parsed = json.loads(item.get("text", ""))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError(f"{tool} returned no structured object payload")


def _call_tool(
    url: str,
    token: str,
    protocol_version: str,
    request_id: int,
    name: str,
    arguments: dict[str, Any],
    *,
    allow_upstream_denial: bool = False,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    status, _, _, payload = rpc(
        url,
        token,
        request_id,
        "tools/call",
        {"name": name, "arguments": arguments},
        protocol_version,
    )
    result = require_result(status, payload, f"tools/call {name}", request_id)
    is_error = require_error_flag(result)
    content = require_content_blocks(result)
    if is_error:
        error_text = _content_text(result)
        if allow_upstream_denial and "not_found_or_unauthorized" in error_text:
            return (
                {
                    "status": status,
                    "is_error": is_error,
                    "content_blocks": len(content),
                    "error": error_text,
                },
                None,
            )
        raise RuntimeError(
            f"{name} returned an MCP tool error: {error_text}"
        )
    return (
        {
            "status": status,
            "is_error": is_error,
            "content_blocks": len(content),
        },
        _structured_payload(result, name),
    )


def _identity(item: dict[str, Any]) -> tuple[str, str]:
    owner = item.get("owner")
    if isinstance(owner, dict):
        owner = owner.get("login") or owner.get("username")
    if not isinstance(owner, str) or not owner.strip():
        full_name = item.get("full_name")
        if isinstance(full_name, str) and "/" in full_name:
            owner = full_name.split("/", 1)[0]
    repo = item.get("name") or item.get("repo")
    if not isinstance(repo, str) or not repo.strip():
        full_name = item.get("full_name")
        if isinstance(full_name, str) and "/" in full_name:
            repo = full_name.split("/", 1)[1]
    if not isinstance(owner, str) or not isinstance(repo, str):
        raise RuntimeError("catalog item is missing a repository identity")
    return owner, repo


def _require_items(payload: dict[str, Any], operation: str) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise RuntimeError(f"{operation} returned an invalid items list")
    return items


def _article_slugs(
    repository: dict[str, Any],
    tree: dict[str, Any],
    file_payload: dict[str, Any] | None,
    repo_name: str,
    article_tree: dict[str, Any] | None = None,
) -> list[str]:
    sources = [json.dumps(repository, ensure_ascii=False)]
    entries = tree.get("entries")
    if isinstance(entries, list):
        sources.append(json.dumps(entries, ensure_ascii=False))
    if article_tree is not None:
        article_entries = article_tree.get("entries")
        if isinstance(article_entries, list):
            sources.append(json.dumps(article_entries, ensure_ascii=False))
    if file_payload is not None:
        sources.append(json.dumps(file_payload, ensure_ascii=False))
    candidates: list[str] = []
    for source in sources:
        for match in ARTICLE_PATH_PATTERN.finditer(source):
            slug = match.group(1).strip()
            if slug.casefold().endswith(".md"):
                slug = slug[:-3]
            if slug and slug not in candidates:
                candidates.append(slug)
    published_slug = repository.get("slug")
    if isinstance(published_slug, str) and published_slug.strip():
        if published_slug not in candidates:
            candidates.append(published_slug.strip())
    if repo_name not in candidates:
        candidates.append(repo_name)
    return candidates


def _preview_is_safe(preview: dict[str, Any]) -> None:
    if preview.get("status") != "preview":
        raise RuntimeError("create_issue preview did not return status=preview")
    confirmation = preview.get("confirmation")
    if not isinstance(confirmation, str) or not confirmation.strip():
        raise RuntimeError("create_issue preview did not return a confirmation")


def _require_knowledge_identity(
    payload: dict[str, Any] | None,
    owner: str,
    repo: str,
    slug: str,
    path: str,
) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError("get_knowledge returned invalid repository identity")
    payload_owner = payload.get("owner")
    if isinstance(payload_owner, dict):
        payload_owner = payload_owner.get("login") or payload_owner.get("username")
    payload_repo = payload.get("repository")
    payload_slug = payload.get("slug")
    payload_path = payload.get("path")
    if not all(
        isinstance(value, str) and value.strip()
        for value in (payload_owner, payload_repo, payload_slug, payload_path)
    ):
        raise RuntimeError("get_knowledge returned invalid repository identity")
    if (
        payload_owner != owner
        or payload_repo != repo
        or payload_slug != slug
        or payload_path.strip("/") != path.strip("/")
    ):
        raise RuntimeError("knowledge article identity mismatch")


def run(
    url: str,
    token_file: Path,
    client: str,
    version: str,
    *,
    issue_owner: str | None = None,
    issue_repo: str | None = None,
    issue_number: int | None = None,
    require_issue_detail: bool = False,
) -> dict[str, Any]:
    require_secure_endpoint(url)
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("token file is empty")

    initialize_params = {
        "protocolVersion": EXPECTED_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": f"{client}-operational-use-cases", "version": version},
    }
    summary: dict[str, Any] = {
        "client": client,
        "client_version": version,
        "secret_exposed": False,
        "use_cases": {},
    }

    unauth_status, _, _, unauth_payload = rpc(
        url, "", 90, "initialize", initialize_params,
    )
    require_auth_rejection(unauth_status, unauth_payload, 90)
    summary["use_cases"]["authentication_boundary"] = {
        "unauthenticated_initialize_status": unauth_status,
        "expected": "401",
    }

    initialize_status, _, _, initialized = rpc(
        url, token, 1, "initialize", initialize_params,
    )
    initialize_result = require_initialize_result(
        initialize_status, initialized, 1,
    )
    protocol_version = initialize_result["protocolVersion"]
    notification = notify_initialized(url, token, protocol_version)

    tools_status, _, _, tools_payload = rpc(
        url, token, 2, "tools/list", {}, protocol_version,
    )
    tools = require_list_result(
        tools_status, tools_payload, "tools/list", "tools", 2,
    )
    require_tool_items(tools)
    for tool in REQUIRED_OPERATIONAL_TOOLS:
        require_advertised_item(tools, tool, "tools/list")

    resources_status, _, _, resources_payload = rpc(
        url, token, 3, "resources/list", {}, protocol_version,
    )
    resources = require_list_result(
        resources_status, resources_payload, "resources/list", "resources", 3,
    )
    require_resource_items(resources)
    require_openapi_resource(resources)
    summary["use_cases"]["agent_bootstrap"] = {
        "initialize_status": initialize_status,
        "initialize_server": initialize_result["serverInfo"],
        "initialized_notification": notification,
        "tools_list_status": tools_status,
        "tools_list_count": len(tools),
        "resources_list_status": resources_status,
        "resources_list_count": len(resources),
    }

    next_tool_id = 10

    def call_tool(
        name: str,
        arguments: dict[str, Any],
        *,
        allow_upstream_denial: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        nonlocal next_tool_id
        result = _call_tool(
            url,
            token,
            protocol_version,
            next_tool_id,
            name,
            arguments,
            allow_upstream_denial=allow_upstream_denial,
        )
        next_tool_id += 1
        return result

    selected_catalog = None
    catalog_pages: list[dict[str, Any]] = []
    skipped_catalog_repositories: list[dict[str, str]] = []
    catalog_page = 1
    while selected_catalog is None and catalog_page <= MAX_CATALOG_PAGES:
        catalog_meta, catalog = call_tool(
            "search_catalog",
            {"kind": "doc", "query": "", "page": catalog_page, "limit": 20},
        )
        catalog_pages.append(catalog_meta)
        catalog_items = _require_items(catalog, "search_catalog")
        for public_doc in catalog_items:
            if (
                public_doc.get("private") is True
                or not isinstance(public_doc.get("owner"), dict)
                or not public_doc.get("name")
            ):
                continue
            candidate_identity = str(public_doc.get("full_name") or public_doc.get("name"))
            try:
                doc_owner, doc_repo = _identity(public_doc)
                candidate_identity = f"{doc_owner}/{doc_repo}"
                repo_meta, repository = call_tool(
                    "get_repository",
                    {"owner": doc_owner, "repo": doc_repo},
                )
                ref = repository.get("default_branch") or "main"
                tree_meta, tree = call_tool(
                    "get_tree",
                    {"owner": doc_owner, "repo": doc_repo, "ref": ref},
                )
                entries = tree.get("entries")
                if not isinstance(entries, list):
                    raise RuntimeError("get_tree returned no root entries")
                articles_entry = next(
                    (
                        entry for entry in entries
                        if isinstance(entry, dict)
                        and entry.get("type") == "dir"
                        and isinstance(entry.get("path"), str)
                        and Path(entry["path"]).name.casefold() == "articles"
                    ),
                    None,
                )
                if articles_entry is None:
                    raise RuntimeError(
                        f"{doc_owner}/{doc_repo} has no articles/ directory in its root tree"
                    )
                articles_path = str(articles_entry["path"]).strip("/")
                articles_tree_meta, articles_tree = call_tool(
                    "get_tree",
                    {
                        "owner": doc_owner,
                        "repo": doc_repo,
                        "ref": ref,
                        "path": articles_path,
                    },
                )
                article_entries = articles_tree.get("entries")
                if not isinstance(article_entries, list):
                    raise RuntimeError("get_tree articles/ returned no entries")
                file_entry = next(
                    (
                        entry for entry in article_entries
                        if isinstance(entry, dict)
                        and entry.get("type") == "file"
                        and isinstance(entry.get("path"), str)
                        and Path(entry["path"]).suffix.casefold() == ".md"
                        and entry["path"].strip()
                    ),
                    None,
                )
                if file_entry is None:
                    raise RuntimeError(
                        f"{doc_owner}/{doc_repo} has no Markdown article in {articles_path}/"
                    )
                file_path = str(file_entry["path"]).strip("/")
                if "/" not in file_path:
                    file_path = f"{articles_path}/{file_path}"
                file_meta, file_payload = call_tool(
                    "get_file",
                    {
                        "owner": doc_owner,
                        "repo": doc_repo,
                        "path": file_path,
                        "ref": ref,
                    },
                )

                knowledge_meta = None
                knowledge_slug = None
                knowledge_errors = []
                knowledge_identity_mismatch = False
                knowledge_candidates = _article_slugs(
                    repository,
                    tree,
                    file_payload,
                    doc_repo,
                    articles_tree,
                )
                for candidate in knowledge_candidates:
                    try:
                        knowledge_meta, knowledge_payload = call_tool(
                            "get_knowledge",
                            {"owner": doc_owner, "slug": candidate},
                        )
                        _require_knowledge_identity(
                            knowledge_payload,
                            doc_owner,
                            doc_repo,
                            candidate,
                            file_path,
                        )
                        knowledge_slug = candidate
                        break
                    except RuntimeError as exc:
                        message = str(exc)
                        if "not_found_or_unauthorized" in message:
                            knowledge_errors.append(message)
                            continue
                        if "knowledge article identity mismatch" in message:
                            knowledge_identity_mismatch = True
                            knowledge_errors.append(message)
                            continue
                        raise
                if knowledge_meta is None or knowledge_slug is None:
                    error_prefix = (
                        "knowledge article identity mismatch"
                        if knowledge_identity_mismatch
                        else "no published Knowledge article slug was found in repository content"
                    )
                    raise RuntimeError(
                        error_prefix + ": "
                        + "; ".join(knowledge_errors)
                    )
                selected_catalog = {
                    "catalog_search": catalog_meta,
                    "repository": repo_meta,
                    "tree": tree_meta,
                    "articles_tree": articles_tree_meta,
                    "file": file_meta,
                    "knowledge": knowledge_meta,
                    "repository_identity": candidate_identity,
                    "tree_ref": ref,
                    "file_path": file_path,
                    "knowledge_slug": knowledge_slug,
                    "catalog_page": catalog_page,
                }
                break
            except RuntimeError as exc:
                message = str(exc)
                if not _catalog_candidate_error_is_skippable(message):
                    raise
                skipped_catalog_repositories.append({
                    "repository": candidate_identity,
                    "reason": _catalog_candidate_skip_reason(message),
                })
        if selected_catalog is not None:
            break
        total_pages = catalog.get("totalPages", catalog_page)
        try:
            total_pages = max(catalog_page, int(total_pages))
        except (TypeError, ValueError):
            total_pages = catalog_page
        if not catalog_items or catalog_page >= total_pages:
            break
        catalog_page += 1
    if selected_catalog is None:
        raise RuntimeError(
            "search_catalog did not yield a published Knowledge repository after "
            f"checking {len(catalog_pages)} page(s)"
        )
    selected_catalog["catalog_pages_checked"] = len(catalog_pages)
    selected_catalog["skipped_catalog_repositories"] = skipped_catalog_repositories
    summary["use_cases"]["catalog_to_knowledge"] = selected_catalog

    repositories_meta, repositories = call_tool(
        "list_repositories",
        {"query": "", "page": 1, "limit": 100},
    )
    repository_items = _require_items(repositories, "list_repositories")
    if not repository_items:
        raise RuntimeError("list_repositories returned no repositories")

    issue_target = None
    if issue_owner and issue_repo:
        issue_target = (issue_owner, issue_repo)
    else:
        issue_target = _identity(repository_items[0])
    require_issue = require_issue_detail or issue_number is not None
    issue_meta, issues = call_tool(
        "list_issues",
        {
            "owner": issue_target[0],
            "repo": issue_target[1],
            "state": "open",
            "page": 1,
            "limit": 20,
        },
        allow_upstream_denial=not require_issue,
    )
    issue_items = _require_items(issues, "list_issues") if issues is not None else []
    issue_detail_meta = None
    selected_issue_number = issue_number
    if selected_issue_number is None and issue_items:
        selected_issue_number = issue_items[0].get("number")
    if selected_issue_number is not None:
        if not isinstance(selected_issue_number, int) or selected_issue_number < 1:
            raise RuntimeError("issue number must be a positive integer")
        issue_detail_meta, _ = call_tool(
            "get_issue",
            {
                "owner": issue_target[0],
                "repo": issue_target[1],
                "number": selected_issue_number,
            },
        )
    elif require_issue:
        raise RuntimeError(
            "issue list was empty; pass an issue target or use a fixture with an issue"
        )
    if issue_meta.get("is_error"):
        detail_status = "skipped_upstream_permission"
    elif issue_detail_meta:
        detail_status = "passed"
    else:
        detail_status = "skipped_no_open_issue"
    summary["use_cases"]["issue_triage"] = {
        "repository_list": repositories_meta,
        "list_issues": issue_meta,
        "open_issue_count": len(issue_items),
        "get_issue": issue_detail_meta,
        "detail_status": detail_status,
        "repository_identity": f"{issue_target[0]}/{issue_target[1]}",
    }

    push_repo = next(
        (
            item for item in repository_items
            if isinstance(item.get("permissions"), dict)
            and item["permissions"].get("push") is True
        ),
        None,
    )
    if push_repo is None:
        raise RuntimeError("list_repositories returned no push-authorized repository")
    push_owner, push_name = _identity(push_repo)
    preview_meta, preview = call_tool(
        "create_issue",
        {
            "owner": push_owner,
            "repo": push_name,
            "title": "NyankoFace operational use-case preview",
            "body": "Preview-only acceptance check; no mutation is requested.",
            "preview": True,
        },
    )
    _preview_is_safe(preview)
    summary["use_cases"]["safe_write_preview"] = {
        "create_issue": preview_meta,
        "preview_status": preview["status"],
        "mutation_executed": False,
        "repository_identity": f"{push_owner}/{push_name}",
    }

    rendered = json.dumps(summary, ensure_ascii=False)
    if token in rendered:
        raise RuntimeError("credential appeared in operational summary")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--client-version", required=True)
    parser.add_argument("--issue-owner")
    parser.add_argument("--issue-repo")
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--require-issue-detail", action="store_true")
    args = parser.parse_args()
    if bool(args.issue_owner) != bool(args.issue_repo):
        parser.error("--issue-owner and --issue-repo must be provided together")

    try:
        summary = run(
            args.url,
            args.token_file,
            args.client,
            args.client_version,
            issue_owner=args.issue_owner,
            issue_repo=args.issue_repo,
            issue_number=args.issue_number,
            require_issue_detail=args.require_issue_detail,
        )
    except Exception as exc:
        message = str(exc)
        try:
            token = args.token_file.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if token and token in message:
            message = "operational use-case check failed without exposing credential"
        print(f"operational use-case check failed: {message}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
