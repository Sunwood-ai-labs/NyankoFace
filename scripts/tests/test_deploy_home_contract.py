import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts/deploy-home.sh").read_text(encoding="utf-8")


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
        self.assertIn('"method":"tools/list"', SCRIPT)
        self.assertIn('"method":"resources/list"', SCRIPT)
        self.assertIn('NYANKOFACE_DEPLOY_MCP_TOKEN_FILE', SCRIPT)

    def test_cleanup_status_collection_is_bounded(self):
        self.assertIn('timeout --signal=KILL 10s', SCRIPT)

    def test_validate_only_does_not_run_the_post_deploy_smoke(self):
        validation = SCRIPT.index('if (( validate_only )); then')
        smoke_call = SCRIPT.rindex('run_public_smoke_test')
        self.assertLess(validation, smoke_call)
        self.assertIn('deployment was not started', SCRIPT[validation:smoke_call])


if __name__ == "__main__":
    unittest.main()
