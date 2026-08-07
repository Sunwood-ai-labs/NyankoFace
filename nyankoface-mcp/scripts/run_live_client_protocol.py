#!/usr/bin/env python3
"""Run secret-safe live MCP read checks with a token loaded from a file."""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


EXPECTED_CATALOG_SCOPE_DENIAL = "Missing required NyankoFace scope: catalog:read"
EXPECTED_PROTOCOL_VERSION = "2025-06-18"
EXPECTED_SERVER_NAME = "NyankoFace"
EXPECTED_AUTH_ERROR_CODE = -32001
EXPECTED_RESOURCE_NAME = "OpenAPI"
EXPECTED_RESOURCE_URI = "nyankoface://api/openapi"
LOOPBACK_HOSTNAMES = {"localhost"}


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Prevent a bearer-bearing request from being redirected."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"refusing HTTP redirect status {code}")


def require_secure_endpoint(url: str) -> None:
    """Allow HTTPS endpoints and HTTP only for local behavioral fixtures."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError as exc:
        raise RuntimeError("endpoint URL is invalid") from exc
    if parsed.scheme == "https" and hostname:
        return
    if parsed.scheme == "http" and hostname:
        if hostname.lower() in LOOPBACK_HOSTNAMES:
            return
        try:
            if ipaddress.ip_address(hostname).is_loopback:
                return
        except ValueError:
            pass
    raise RuntimeError(
        "bearer endpoint must use HTTPS; HTTP is allowed only for loopback fixtures"
    )


def require_result(
    status: int,
    payload: Any,
    method: str,
    request_id: int,
) -> dict[str, Any]:
    if status != 200:
        raise RuntimeError(f"{method} returned unexpected HTTP status {status}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} returned a non-object JSON-RPC response")
    if payload.get("jsonrpc") != "2.0":
        raise RuntimeError(f"{method} returned an invalid JSON-RPC version")
    if not has_matching_request_id(payload, request_id):
        raise RuntimeError(f"{method} returned an unexpected JSON-RPC id")
    if "error" in payload:
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else "unknown"
        raise RuntimeError(f"{method} returned JSON-RPC error {code}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"{method} response is missing an object result")
    return result


def require_list_result(
    status: int,
    payload: Any,
    method: str,
    field: str,
    request_id: int,
) -> list[dict[str, Any]]:
    result = require_result(status, payload, method, request_id)
    items = result.get(field)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise RuntimeError(f"{method} result is missing the {field} list")
    return items


def require_initialize_result(status: int, payload: Any, request_id: int) -> dict[str, Any]:
    result = require_result(status, payload, "initialize", request_id)
    if result.get("protocolVersion") != EXPECTED_PROTOCOL_VERSION:
        raise RuntimeError("initialize returned an unsupported protocolVersion")
    server = result.get("serverInfo")
    if not isinstance(server, dict):
        raise RuntimeError("initialize result is missing serverInfo")
    if server.get("name") != EXPECTED_SERVER_NAME:
        raise RuntimeError("initialize returned an unexpected serverInfo.name")
    version = server.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("initialize returned an invalid serverInfo.version")
    capabilities = result.get("capabilities")
    if not isinstance(capabilities, dict):
        raise RuntimeError("initialize result is missing capabilities")
    for capability in ("tools", "resources"):
        if not isinstance(capabilities.get(capability), dict):
            raise RuntimeError(
                f"initialize result is missing {capability} capability"
            )
    return result


def require_auth_rejection(status: int, payload: Any, request_id: int) -> None:
    if status != 401:
        raise RuntimeError(f"authentication returned unexpected HTTP status {status}")
    if isinstance(payload, dict) and payload.get("jsonrpc") == "2.0":
        if not has_matching_request_id(payload, request_id):
            raise RuntimeError("authentication response has an unexpected JSON-RPC id")
        error = payload.get("error")
        if not isinstance(error, dict) or error.get("code") != EXPECTED_AUTH_ERROR_CODE:
            raise RuntimeError("authentication response is missing the expected error code")
        return
    if isinstance(payload, dict) and payload.get("error") == "invalid_token":
        return
    raise RuntimeError("authentication response is neither a JSON-RPC nor OAuth error")


def require_base64_payload(value: Any, error_message: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(error_message)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(error_message) from exc
    if not decoded:
        raise RuntimeError(error_message)


def require_content_blocks(call_result: dict[str, Any]) -> list[dict[str, Any]]:
    content = call_result.get("content")
    if not isinstance(content, list) or not content:
        raise RuntimeError("tools/call result is missing a non-empty content list")
    for item in content:
        if not isinstance(item, dict):
            raise RuntimeError("tools/call result contains an invalid content block")
        item_type = item.get("type")
        if item_type == "text":
            if not isinstance(item.get("text"), str) or not item["text"].strip():
                raise RuntimeError("tools/call result contains empty text content")
        elif item_type in {"image", "audio"}:
            if (
                not isinstance(item.get("data"), str)
                or not item["data"].strip()
                or not isinstance(item.get("mimeType"), str)
                or not item["mimeType"].strip()
            ):
                raise RuntimeError(f"tools/call result contains invalid {item_type} content")
            require_base64_payload(
                item["data"],
                f"tools/call result contains invalid {item_type} content",
            )
        elif item_type == "resource":
            resource = item.get("resource")
            if (
                not isinstance(resource, dict)
                or not isinstance(resource.get("uri"), str)
                or not resource["uri"].strip()
            ):
                raise RuntimeError("tools/call result contains invalid resource content")
            if not (
                isinstance(resource.get("text"), str) and resource["text"].strip()
                or isinstance(resource.get("blob"), str) and resource["blob"].strip()
            ):
                raise RuntimeError("tools/call result contains an empty embedded resource")
            blob = resource.get("blob")
            if blob is not None:
                require_base64_payload(
                    blob,
                    "tools/call result contains an invalid embedded resource blob",
                )
        elif item_type == "resource_link":
            if (
                not isinstance(item.get("name"), str)
                or not item["name"].strip()
                or not isinstance(item.get("uri"), str)
                or not item["uri"].strip()
            ):
                raise RuntimeError("tools/call result contains invalid resource link content")
        else:
            raise RuntimeError("tools/call result contains an unsupported content block")
    return content


def require_error_flag(call_result: dict[str, Any]) -> bool:
    is_error = call_result.get("isError", False)
    if not isinstance(is_error, bool):
        raise RuntimeError("tools/call result contains an invalid isError flag")
    return is_error


def require_advertised_item(
    items: list[dict[str, Any]],
    name: str,
    method: str,
) -> None:
    if not any(item.get("name") == name for item in items):
        raise RuntimeError(f"{method} did not advertise {name}")


def require_tool_items(items: list[dict[str, Any]]) -> None:
    for item in items:
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError("tools/list contains a tool without a valid name")
        if not isinstance(item.get("inputSchema"), dict):
            raise RuntimeError(
                f"tools/list tool {name!r} is missing a valid inputSchema"
            )


def require_resource_items(items: list[dict[str, Any]]) -> None:
    for item in items:
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError("resources/list contains a resource without a valid name")
        uri = item.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            raise RuntimeError(
                f"resources/list resource {name!r} is missing a valid uri"
            )


def require_openapi_resource(items: list[dict[str, Any]]) -> None:
    """Require the OpenAPI resource URI regardless of its display name."""
    if any(item.get("uri") == EXPECTED_RESOURCE_URI for item in items):
        return
    raise RuntimeError("resources/list did not advertise the OpenAPI resource")


def parse_sse_response(raw: str, request_id: int) -> dict[str, Any]:
    """Decode complete SSE events and return the response for this request."""
    data_lines: list[str] = []
    matches: list[dict[str, Any]] = []

    def finish_event() -> None:
        if not data_lines:
            return
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise RuntimeError("SSE event contains invalid JSON") from exc
        if isinstance(payload, dict) and has_matching_request_id(payload, request_id):
            matches.append(payload)

    for line in raw.splitlines():
        if not line:
            finish_event()
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if field != "data":
            continue
        if separator and value.startswith(" "):
            value = value[1:]
        data_lines.append(value)
    finish_event()

    if not matches:
        raise RuntimeError(
            f"SSE response did not contain a JSON-RPC response for request id {request_id}"
        )
    if len(matches) > 1:
        raise RuntimeError(
            f"SSE response contained multiple JSON-RPC responses for request id {request_id}"
        )
    return matches[0]


def has_matching_request_id(payload: dict[str, Any], request_id: int) -> bool:
    actual_id = payload.get("id")
    return (
        isinstance(actual_id, int)
        and not isinstance(actual_id, bool)
        and actual_id == request_id
    )


def response_media_type(content_type: str) -> str:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"application/json", "text/event-stream"}:
        raise RuntimeError(
            "MCP response has an unsupported Content-Type; expected "
            "application/json or text/event-stream"
        )
    return media_type


def rpc(
    url: str,
    token: str,
    request_id: int,
    method: str,
    params: dict[str, Any],
    protocol_version: str | None = None,
):
    body = json.dumps({
        "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
    }).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        response = urllib.request.build_opener(RejectRedirects).open(request, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        raw = response.read().decode("utf-8")
        content_type = response_media_type(response.headers.get("content-type", ""))
        instance = response.headers.get("x-nyankoface-mcp-instance", "")
        if content_type == "text/event-stream":
            payload = parse_sse_response(raw, request_id)
        else:
            payload = json.loads(raw)
        return response.status, content_type, instance, payload


def notify_initialized(url: str, token: str, protocol_version: str) -> dict[str, int]:
    body = json.dumps({
        "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
    }).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": protocol_version,
    })
    try:
        response = urllib.request.build_opener(RejectRedirects).open(request, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        raw = response.read()
        if response.status != 202 or raw:
            raise RuntimeError(
                "notifications/initialized must return an empty HTTP 202 response "
                f"(got {response.status} with {len(raw)} body bytes)"
            )
        return {"status": response.status, "body_bytes": len(raw)}


def run(
    url: str,
    token_file: Path,
    client: str,
    version: str,
    read_mode: str = "catalog",
) -> dict[str, Any]:
    require_secure_endpoint(url)
    token = token_file.read_text(encoding="utf-8").strip()
    summary: dict[str, Any] = {
        "endpoint": url, "client": client, "client_version": version,
        "secret_exposed": False,
    }
    status, content_type, instance, initialized = rpc(url, token, 1, "initialize", {
        "protocolVersion": EXPECTED_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": f"{client}-live-qa", "version": version},
    })
    if status != 200:
        require_auth_rejection(status, initialized, 1)
    initial_result = initialized.get("result", {}) if isinstance(initialized, dict) else {}
    summary["initialize"] = {
        "status": status, "content_type": content_type, "instance": instance,
        "protocol": initial_result.get("protocolVersion"),
        "server": initial_result.get("serverInfo", {}),
    }
    if status != 200:
        summary["auth_rejected"] = True
        if token and token in json.dumps(summary, ensure_ascii=False):
            raise RuntimeError("credential appeared in diagnostic output")
        return summary
    initialize_result = require_initialize_result(status, initialized, 1)
    negotiated_protocol = initialize_result["protocolVersion"]
    summary["initialize"]["protocol"] = initialize_result.get("protocolVersion")
    summary["initialize"]["server"] = initialize_result.get("serverInfo", {})
    summary["initialized_notification"] = notify_initialized(
        url, token, negotiated_protocol,
    )
    status, _, instance, tools = rpc(
        url, token, 2, "tools/list", {}, negotiated_protocol,
    )
    tool_items = require_list_result(
        status, tools, "tools/list", "tools", 2,
    )
    require_tool_items(tool_items)
    expected_tool = "search_catalog" if read_mode == "catalog" else "get_repository"
    require_advertised_item(tool_items, expected_tool, "tools/list")
    summary["tools_list"] = {
        "status": status, "count": len(tool_items), "instance": instance,
        "representative": [item.get("name") for item in tool_items[:5]],
    }
    status, _, instance, resources = rpc(
        url, token, 3, "resources/list", {}, negotiated_protocol,
    )
    resource_items = require_list_result(
        status, resources, "resources/list", "resources", 3,
    )
    require_resource_items(resource_items)
    require_openapi_resource(resource_items)
    summary["resources_list"] = {
        "status": status, "count": len(resource_items), "instance": instance,
        "representative": [item.get("name") for item in resource_items[:3]],
    }
    read_request = ({
        "name": "search_catalog",
        "arguments": {"kind": "model", "query": "sample", "page": 1, "limit": 3},
    } if read_mode == "catalog" else {
        "name": "get_repository",
        "arguments": {"owner": "nyankoface", "repo": "sample-model"},
    })
    status, _, instance, called = rpc(
        url, token, 4, "tools/call", read_request, negotiated_protocol,
    )
    call_result = require_result(status, called, "tools/call", 4)
    is_error = require_error_flag(call_result)
    content = require_content_blocks(call_result)
    summary["representative_read"] = {
        "status": status, "instance": instance,
        "mode": read_mode,
        "is_error": is_error,
        "content_blocks": len(content),
    }
    if is_error and content:
        summary["representative_read"]["error"] = "\n".join(
            str(item.get("text", "")) for item in content if item.get("type") == "text"
        )
    if token and token in json.dumps(summary, ensure_ascii=False):
        raise RuntimeError("credential appeared in diagnostic output")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("--client-version", required=True)
    parser.add_argument("--read-mode", choices=("catalog", "repository"), default="catalog")
    parser.add_argument("--expected-initialize-status", type=int, default=200)
    parser.add_argument(
        "--expect-read-error",
        action="store_true",
        help="expect the catalog read to be denied specifically for missing catalog:read",
    )
    args = parser.parse_args()
    summary = run(args.url, args.token_file, args.client, args.client_version, args.read_mode)
    if summary["initialize"]["status"] != args.expected_initialize_status:
        raise RuntimeError("unexpected initialize status")
    if args.expected_initialize_status == 200:
        read = summary["representative_read"]
        if args.expect_read_error and (
            args.read_mode != "catalog"
            or not read["is_error"]
            or EXPECTED_CATALOG_SCOPE_DENIAL not in read.get("error", "")
        ):
            raise RuntimeError("expected the specific missing catalog:read denial")
        if not args.expect_read_error and read["is_error"]:
            raise RuntimeError("unexpected representative read result")
        if not args.expect_read_error and read["content_blocks"] < 1:
            raise RuntimeError("representative read returned no content")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
