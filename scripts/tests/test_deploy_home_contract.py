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

    def test_mcp_smoke_check_validates_the_public_metadata_origin(self):
        self.assertIn('"/mcp"', SCRIPT)
        self.assertIn('resource_metadata=', SCRIPT)
        self.assertIn('MCP metadata origin does not match the public URL', SCRIPT)

    def test_validate_only_does_not_run_the_post_deploy_smoke(self):
        validation = SCRIPT.index('if (( validate_only )); then')
        smoke_call = SCRIPT.rindex('run_public_smoke_test')
        self.assertLess(validation, smoke_call)
        self.assertIn('deployment was not started', SCRIPT[validation:smoke_call])


if __name__ == "__main__":
    unittest.main()
