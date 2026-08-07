import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def section(markdown: str, heading: str) -> str:
    start = markdown.index(heading)
    next_heading = markdown.find("\n## ", start + len(heading))
    return markdown[start:] if next_heading == -1 else markdown[start:next_heading]


COMMON_MARKERS = (
    "docker compose --profile mcp config --quiet",
    "docker compose --profile mcp up -d --build frontend gateway nyankoface-mcp mcp-admin",
    "nyankoface-mcp-admin-internal-token",
    "https://<NYANKOFACE_HOST>/mcp",
    "MCP Streamable HTTP",
    "NYANKOFACE_MCP_JSON_RESPONSE=true",
    "/admin/mcp",
    "catalog:read",
    "repos:read",
    "nyankoface/example=read",
    "Codex CLI",
    "Claude Desktop",
    "VS Code",
    "NYANKOFACE_MCP_REMOTE_URL",
    "NYANKOFACE_MCP_CLIENT_TOKEN_FILE",
    "nyankoface-mcp-stdio",
    "tools/list",
    "resources/list",
    "nyankoface-mcp validate-config",
    "rollback",
    "uninstall",
    "revoke",
    "docs/guide/mcp-server.md",
    "docs/guide/mcp-administration.md",
    "docs/guide/mcp-live-clients.md",
    "nyankoface-mcp/examples/vscode-mcp.json",
    "python -m pip install --upgrade ./nyankoface-mcp",
)

POWERSHELL_BOOTSTRAP_MARKERS = (
    "Test-Path -LiteralPath",
    "RandomNumberGenerator]::Create()",
    "File]::WriteAllText",
    "$forgejoTokenPath",
    "throw",
)


class McpReadmeContractTests(unittest.TestCase):
    def test_english_readme_contains_the_complete_mcp_setup_contract(self):
        readme = read("README.md")
        setup = section(readme, "## 🔌 MCP Server setup")
        for marker in COMMON_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, setup)
        self.assertIn("remote custom connector", setup)
        self.assertIn("secret store", setup)
        for marker in POWERSHELL_BOOTSTRAP_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, setup)
        self.assertNotRegex(setup, r"(?:ghp_|glpat-|gitea_|Bearer\s+[A-Za-z0-9]{20,})")

    def test_japanese_readme_contains_the_same_mcp_setup_contract(self):
        readme = read("README.ja.md")
        setup = section(readme, "## 🔌 MCP Serverの設定")
        for marker in COMMON_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, setup)
        self.assertIn("remote custom connector", setup)
        self.assertIn("secret store", setup)
        for marker in POWERSHELL_BOOTSTRAP_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, setup)
        self.assertNotRegex(setup, r"(?:ghp_|glpat-|gitea_|Bearer\s+[A-Za-z0-9]{20,})")

    def test_live_client_guides_require_host_replacement_after_copying_vscode_template(self):
        english = read("docs/guide/mcp-live-clients.md")
        japanese = read("docs/ja/guide/mcp-live-clients.md")
        self.assertIn("copy", english)
        self.assertIn("`<NYANKOFACE_HOST>` host placeholder", english)
        self.assertIn("コピー", japanese)
        self.assertIn("`<NYANKOFACE_HOST>` のhost", japanese)

    def test_readmes_reference_existing_mcp_sources(self):
        for path in (
            "docs/guide/mcp-server.md",
            "docs/guide/mcp-administration.md",
            "docs/guide/mcp-live-clients.md",
            "nyankoface-mcp/examples/vscode-mcp.json",
        ):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())


if __name__ == "__main__":
    unittest.main()
