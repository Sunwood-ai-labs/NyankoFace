import unittest
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/deploy-home.sh"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    drive = path.drive.rstrip(":").lower()
    return f"/mnt/{drive}{path.as_posix()[2:]}"


class DeployHomeContractTests(unittest.TestCase):
    def test_deploy_runs_public_smoke_checks_after_service_readiness(self):
        self.assertIn('run_public_smoke_test', SCRIPT)
        self.assertIn('"/git/api/v1/version"', SCRIPT)
        self.assertIn('"/api/catalog/repositories?limit=1"', SCRIPT)
        self.assertIn('"NyankoFace"', SCRIPT)
        self.assertIn('"SimpleHTTP|TIDELINE"', SCRIPT)
        self.assertIn('PUBLIC_BASE_URL or NYANKOFACE_DEPLOY_SMOKE_BASE_URL is required', SCRIPT)
        self.assertNotIn('base_url:-https://localhost:8443', SCRIPT)

    def test_mcp_smoke_check_validates_the_public_metadata_origin(self):
        self.assertIn('"/mcp"', SCRIPT)
        self.assertIn('resource_metadata=', SCRIPT)
        self.assertIn('MCP metadata origin does not match the public URL', SCRIPT)
        self.assertIn('"method":"initialize"', SCRIPT)
        self.assertIn('"method":"notifications/initialized"', SCRIPT)
        self.assertIn('"method":"tools/list"', SCRIPT)
        self.assertIn('"method":"resources/list"', SCRIPT)
        self.assertIn('"method":"tools/call"', SCRIPT)
        self.assertIn('list_repositories', SCRIPT)
        self.assertIn('MCP-Protocol-Version', SCRIPT)
        self.assertIn('"protocolVersion"', SCRIPT)
        self.assertNotIn('tolower($1) == "mcp-protocol-version:"', SCRIPT)
        self.assertIn('NYANKOFACE_MCP_FORGEJO_USER_TOKEN_FILE', SCRIPT)
        self.assertNotIn('NYANKOFACE_DEPLOY_MCP_TOKEN_FILE:-', SCRIPT)
        self.assertIn('curl_options=(-q', SCRIPT)
        self.assertIn('apostrophe = sprintf("%c", 39)', SCRIPT)
        self.assertIn('JSON-RPC response id does not match the request', SCRIPT)
        self.assertIn('--config -', SCRIPT)
        self.assertNotIn('mcp_header_file', SCRIPT)
        self.assertIn('requires HTTPS before forwarding the bearer token', SCRIPT)
        self.assertNotIn('"$base_url" == https://localhost*', SCRIPT)

    def test_cleanup_status_collection_is_bounded(self):
        self.assertIn('timeout --signal=KILL 10s', SCRIPT)

    def test_validate_only_does_not_run_the_post_deploy_smoke(self):
        validation = SCRIPT.index('if (( validate_only )); then')
        smoke_call = SCRIPT.rindex('run_public_smoke_test')
        self.assertLess(validation, smoke_call)
        self.assertIn('deployment was not started', SCRIPT[validation:smoke_call])

    @unittest.skipUnless(shutil.which("bash"), "bash is required for the smoke integration test")
    def test_public_smoke_executes_authenticated_mcp_contract(self):
        with tempfile.TemporaryDirectory(prefix="nyankoface-deploy-test-") as raw_tmp:
            tmp = Path(raw_tmp)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            env_file = tmp / "deploy.env"
            env_file.write_text("PUBLIC_BASE_URL=https://public.example\n", encoding="utf-8")
            cert_dir = tmp / "certs"
            cert_dir.mkdir()
            token_file = tmp / "mcp-token"
            token_file.write_text("smoke-token", encoding="utf-8")

            docker = fake_bin / "docker"
            docker.write_bytes(
                """#!/usr/bin/env python3
import sys

args = sys.argv[1:]
if args == ["info"]:
    raise SystemExit(0)
if "config" in args and "--services" in args:
    print("frontend")
    print("nyankoface-mcp")
if "ps" in args and "--format" in args:
    print("frontend|running|healthy|0")
    print("nyankoface-mcp|running|healthy|0")
raise SystemExit(0)
""".encode("utf-8")
            )
            curl = fake_bin / "curl"
            curl.write_bytes(
                """#!/usr/bin/env python3
import sys
from pathlib import Path

args = sys.argv[1:]
def option(name):
    index = args.index(name)
    return args[index + 1]

if "--config" in args:
    config = sys.stdin.read()
    if 'Authorization: Bearer smoke-token' not in config:
        raise SystemExit(9)
else:
    config = ""

url = args[-1]
path = url.split("public.example", 1)[-1].split("?", 1)[0]
if path == "/":
    code, headers, body = 200, "content-type: text/html\\n", "<title>NyankoFace</title>"
elif path == "/git/api/v1/version":
    code, headers, body = 200, "content-type: application/json\\n", '{"version":"fixture"}'
elif path == "/api/catalog/repositories":
    code, headers, body = 200, "content-type: application/json\\n", '{"ok":true,"data":[],"total_count":0}'
elif path == "/mcp" and not config:
    code = 401
    headers = 'www-authenticate: Bearer resource_metadata="https://public.example/.well-known/oauth-protected-resource/mcp"\\n'
    body = '{"error":"unauthorized"}'
elif path == "/mcp":
    data = option("--data")
    code, headers = 200, "content-type: application/json\\n"
    if '"method":"initialize"' in data:
        body = '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","serverInfo":{"name":"fixture"}}}'
    elif '"method":"notifications/initialized"' in data:
        if 'MCP-Protocol-Version: 2025-06-18' not in config:
            raise SystemExit(10)
        code, body = 202, ""
    elif '"method":"tools/list"' in data:
        if 'MCP-Protocol-Version: 2025-06-18' not in config:
            raise SystemExit(10)
        body = '{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}'
    elif '"method":"resources/list"' in data:
        if 'MCP-Protocol-Version: 2025-06-18' not in config:
            raise SystemExit(10)
        body = '{"jsonrpc":"2.0","id":3,"result":{"resources":[]}}'
    elif '"method":"tools/call"' in data:
        if 'MCP-Protocol-Version: 2025-06-18' not in config:
            raise SystemExit(10)
        body = '{"jsonrpc":"2.0","id":4,"result":{"content":[]}}'
    else:
        body = '{"error":{"message":"unexpected method"}}'
else:
    code, headers, body = 404, "content-type: text/plain\\n", "not found"

Path(option("--dump-header")).write_text(headers, encoding="utf-8")
Path(option("--output")).write_text(body, encoding="utf-8")
sys.stdout.write(str(code))
""".encode("utf-8")
            )
            for executable in (docker, curl):
                executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

            environment = os.environ.copy()
            fake_bin_for_bash = _bash_path(fake_bin)
            env_file_for_bash = _bash_path(env_file)
            cert_dir_for_bash = _bash_path(cert_dir)
            token_file_for_bash = _bash_path(token_file)
            if os.name == "nt":
                bash_env = tmp / "bash-env"
                bash_env.write_bytes(
                    ("\n".join([
                        f"docker() {{ python3 {shlex.quote(fake_bin_for_bash + '/docker')} \"$@\"; }}",
                        f"curl() {{ python3 {shlex.quote(fake_bin_for_bash + '/curl')} \"$@\"; }}",
                        "git() { printf 'fixture-sha\\n'; }",
                    ]) + "\n").encode("utf-8")
                )
            environment.update({
                "PATH": (
                    f"{fake_bin_for_bash}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
                    if os.name == "nt"
                    else f"{fake_bin_for_bash}{os.pathsep}{environment['PATH']}"
                ),
                "NYANKOFACE_DEPLOY_ENV_FILE": env_file_for_bash,
                "NYANKOFACE_GATEWAY_CERT_DIR": cert_dir_for_bash,
                "NYANKOFACE_DEPLOY_REF": "refs/heads/main",
                "NYANKOFACE_DEPLOY_SMOKE_BASE_URL": "https://public.example",
                "NYANKOFACE_DEPLOY_TIMEOUT_SECONDS": "5",
                "NYANKOFACE_DEPLOY_SMOKE_TIMEOUT_SECONDS": "5",
                "NYANKOFACE_MCP_FORGEJO_USER_TOKEN_FILE": token_file_for_bash,
            })
            if os.name == "nt":
                environment["BASH_ENV"] = _bash_path(bash_env)
                exports = " ".join(
                    f"export {key}={shlex.quote(value)};"
                    for key, value in environment.items()
                    if key.startswith("NYANKOFACE_") or key in {"PATH", "BASH_ENV"}
                )
                command = f"{exports} exec bash {shlex.quote(_bash_path(SCRIPT_PATH))}"
                invocation = ["bash", "-lc", command]
                invocation_environment = None
            else:
                invocation = ["bash", _bash_path(SCRIPT_PATH)]
                invocation_environment = environment
            result = subprocess.run(
                invocation,
                cwd=ROOT,
                env=invocation_environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("public deployment smoke test passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
