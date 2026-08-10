import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_operational_use_cases import run  # noqa: E402


class _OperationalFixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = []
    preview_requests = []
    mutations = []
    deny_issue_reads = False
    invalid_first_catalog_candidate = False
    fatal_invalid_catalog_candidate = False

    def log_message(self, _format, *_args):
        return

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if not token:
            self._send_json(401, {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32001, "message": "authentication rejected"},
            })
            return

        method = request["method"]
        if method == "notifications/initialized":
            self._send_empty(202)
            return
        if method == "initialize":
            self._send_json(200, {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "NyankoFace", "version": "fixture"},
                    "capabilities": {"tools": {}, "resources": {}},
                },
            })
            return
        if method == "tools/list":
            names = (
                "search_catalog", "list_repositories", "get_repository",
                "get_tree", "get_file", "get_knowledge", "list_issues",
                "get_issue", "create_issue",
            )
            self._send_json(200, {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "tools": [
                        {"name": name, "inputSchema": {"type": "object"}}
                        for name in names
                    ],
                },
            })
            return
        if method == "resources/list":
            self._send_json(200, {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "resources": [{
                        "name": "OpenAPI",
                        "uri": "nyankoface://api/openapi",
                    }],
                },
            })
            return
        if method != "tools/call":
            self._send_json(400, {"error": "unexpected method"})
            return

        params = request["params"]
        name = params["name"]
        arguments = params.get("arguments", {})
        type(self).calls.append((name, arguments))
        if name == "search_catalog":
            if (
                type(self).invalid_first_catalog_candidate
                and arguments.get("page") == 1
            ):
                items = [{
                    "owner": {"login": "bob"},
                    "name": "empty",
                    "full_name": "bob/empty",
                    "private": False,
                }]
                total_pages = 2
            else:
                items = [{
                    "owner": {"login": "alice"},
                    "name": "knowledge",
                    "full_name": "alice/knowledge",
                    "private": False,
                }]
                total_pages = 1
            value = {
                "kind": "doc",
                "page": arguments.get("page", 1),
                "limit": arguments.get("limit", 20),
                "totalPages": total_pages,
                "items": items,
            }
        elif name == "list_repositories":
            value = {
                "items": [{
                    "owner": {"login": "alice"},
                    "name": "knowledge",
                    "full_name": "alice/knowledge",
                    "private": False,
                    "default_branch": "main",
                    "open_issues_count": 1,
                    "permissions": {"pull": True, "push": True},
                }],
                "page": 1,
                "limit": 100,
                "totalCount": 1,
            }
        elif name == "get_repository":
            if (
                type(self).fatal_invalid_catalog_candidate
                and arguments.get("repo") == "empty"
            ):
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {
                        "isError": True,
                        "content": [{
                            "type": "text",
                            "text": (
                                "Error executing tool get_repository: "
                                '{"error":{"code":"invalid_upstream_response"}}'
                            ),
                        }],
                    },
                })
                return
            value = {
                "owner": arguments["owner"],
                "name": arguments["repo"],
                "full_name": f'{arguments["owner"]}/{arguments["repo"]}',
                "default_branch": "main",
                "permissions": {"pull": True, "push": True},
            }
        elif name == "get_tree":
            if arguments.get("path") == "articles":
                value = {
                    "owner": arguments["owner"],
                    "repo": arguments["repo"],
                    "ref": arguments["ref"],
                    "path": "articles",
                    "entries": [{"type": "file", "path": "articles/fixture-article.md"}],
                }
            else:
                entries = (
                    [{"type": "file", "path": "README.md"}]
                    if arguments.get("repo") == "empty"
                    else [
                        {"type": "dir", "path": "articles"},
                        {"type": "file", "path": "README.md"},
                    ]
                )
                value = {
                    "owner": arguments["owner"],
                    "repo": arguments["repo"],
                    "ref": arguments["ref"],
                    "path": None,
                    "entries": entries,
                }
        elif name == "get_file":
            value = {
                "path": arguments["path"],
                "ref": arguments["ref"],
                "text": "Published article: articles/fixture-article.md",
            }
        elif name == "get_knowledge":
            value = {
                "owner": arguments["owner"],
                "slug": arguments["slug"],
                "title": "Operational fixture knowledge",
            }
        elif name == "list_issues":
            if type(self).deny_issue_reads:
                value = None
                self._send_json(200, {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {
                        "isError": True,
                        "content": [{
                            "type": "text",
                            "text": (
                                "Error executing tool list_issues: "
                                '{"error":{"code":"not_found_or_unauthorized"}}'
                            ),
                        }],
                    },
                })
                return
            value = {
                "items": [{"number": 7, "title": "triage me", "state": "open"}],
            }
        elif name == "get_issue":
            value = {"number": arguments["number"], "title": "triage me", "state": "open"}
        elif name == "create_issue":
            assert arguments["preview"] is True
            type(self).preview_requests.append(arguments)
            value = {
                "status": "preview",
                "confirmation": "fixture-confirmation",
                "confirmation_expires_at": 4_102_444_800,
            }
        else:
            self._send_json(400, {"error": f"unexpected tool {name}"})
            return

        self._send_json(200, {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "isError": False,
                "structuredContent": value,
                "content": [{"type": "text", "text": json.dumps(value)}],
            },
        })


def test_operational_use_case_runner_covers_agent_workflows_without_mutation(tmp_path):
    _OperationalFixture.calls = []
    _OperationalFixture.preview_requests = []
    _OperationalFixture.mutations = []
    _OperationalFixture.deny_issue_reads = False
    _OperationalFixture.invalid_first_catalog_candidate = False
    _OperationalFixture.fatal_invalid_catalog_candidate = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OperationalFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = "operational-fixture-secret"
    token_file = tmp_path / "forgejo.token"
    token_file.write_text(token, encoding="utf-8")
    try:
        summary = run(
            f"http://127.0.0.1:{server.server_port}/mcp",
            token_file,
            "fixture-agent",
            "1.0",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    use_cases = summary["use_cases"]
    assert use_cases["authentication_boundary"]["unauthenticated_initialize_status"] == 401
    assert use_cases["agent_bootstrap"]["tools_list_count"] == 9
    assert use_cases["catalog_to_knowledge"]["knowledge"]["status"] == 200
    assert use_cases["catalog_to_knowledge"]["file_path"] == "articles/fixture-article.md"
    assert use_cases["catalog_to_knowledge"]["knowledge_slug"] == "fixture-article"
    assert (
        "get_tree",
        {"owner": "alice", "repo": "knowledge", "ref": "main", "path": "articles"},
    ) in _OperationalFixture.calls
    assert use_cases["issue_triage"]["detail_status"] == "passed"
    assert use_cases["safe_write_preview"]["preview_status"] == "preview"
    assert use_cases["safe_write_preview"]["mutation_executed"] is False
    assert len(_OperationalFixture.preview_requests) == 1
    assert _OperationalFixture.mutations == []
    assert all(name != "update_issue" for name, _arguments in _OperationalFixture.calls)
    assert "instance" not in json.dumps(summary)
    assert "endpoint" not in summary
    assert token not in json.dumps(summary)


def test_operational_use_case_runner_skips_invalid_catalog_candidate_and_pages(tmp_path):
    _OperationalFixture.calls = []
    _OperationalFixture.preview_requests = []
    _OperationalFixture.mutations = []
    _OperationalFixture.deny_issue_reads = False
    _OperationalFixture.invalid_first_catalog_candidate = True
    _OperationalFixture.fatal_invalid_catalog_candidate = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OperationalFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "forgejo.token"
    token_file.write_text("paged-fixture-secret", encoding="utf-8")
    try:
        summary = run(
            f"http://127.0.0.1:{server.server_port}/mcp",
            token_file,
            "fixture-agent",
            "1.0",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _OperationalFixture.invalid_first_catalog_candidate = False

    catalog_use_case = summary["use_cases"]["catalog_to_knowledge"]
    assert catalog_use_case["catalog_page"] == 2
    assert catalog_use_case["catalog_pages_checked"] == 2
    assert catalog_use_case["repository_identity"] == "alice/knowledge"
    assert catalog_use_case["skipped_catalog_repositories"] == [{
        "repository": "bob/empty",
        "reason": "missing_articles_directory",
    }]


def test_operational_use_case_runner_does_not_skip_fatal_upstream_response(tmp_path):
    _OperationalFixture.calls = []
    _OperationalFixture.preview_requests = []
    _OperationalFixture.mutations = []
    _OperationalFixture.deny_issue_reads = False
    _OperationalFixture.invalid_first_catalog_candidate = True
    _OperationalFixture.fatal_invalid_catalog_candidate = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OperationalFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "forgejo.token"
    token_file.write_text("fatal-fixture-secret", encoding="utf-8")
    try:
        with pytest.raises(RuntimeError, match="invalid_upstream_response"):
            run(
                f"http://127.0.0.1:{server.server_port}/mcp",
                token_file,
                "fixture-agent",
                "1.0",
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _OperationalFixture.invalid_first_catalog_candidate = False
        _OperationalFixture.fatal_invalid_catalog_candidate = False


def test_operational_use_case_runner_records_missing_issue_scope_without_false_success(tmp_path):
    _OperationalFixture.calls = []
    _OperationalFixture.preview_requests = []
    _OperationalFixture.mutations = []
    _OperationalFixture.deny_issue_reads = True
    _OperationalFixture.invalid_first_catalog_candidate = False
    _OperationalFixture.fatal_invalid_catalog_candidate = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OperationalFixture)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "forgejo.token"
    token_file.write_text("repo-only-fixture-secret", encoding="utf-8")
    try:
        summary = run(
            f"http://127.0.0.1:{server.server_port}/mcp",
            token_file,
            "fixture-agent",
            "1.0",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        _OperationalFixture.deny_issue_reads = False

    issue_triage = summary["use_cases"]["issue_triage"]
    assert issue_triage["detail_status"] == "skipped_upstream_permission"
    assert "not_found_or_unauthorized" in issue_triage["list_issues"]["error"]
    assert summary["use_cases"]["safe_write_preview"]["preview_status"] == "preview"
    assert _OperationalFixture.mutations == []
