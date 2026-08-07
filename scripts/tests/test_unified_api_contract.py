import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs" / "contracts" / "nyankoface-api-v1-security.json"


class UnifiedApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_public_namespace_and_openapi_are_versioned(self):
        self.assertEqual(self.contract["public_base_path"], "/api/v1")
        self.assertEqual(self.contract["openapi_path"], "/api/v1/openapi.json")

    def test_opaque_token_generation_audience_and_scope_ceiling_are_explicit(self):
        token = self.contract["token"]
        self.assertEqual(token["generation"], "cryptographically-secure-random")
        self.assertGreaterEqual(token["minimum_entropy_bits"], 256)
        self.assertEqual(token["audience"], "nyankoface-api-v1")
        self.assertEqual(
            token["issuance"]["scope_ceiling"],
            "intersection-of-requested-scopes-and-current-issuer-scope-grants",
        )
        self.assertIn("scope-only-global-token", token["issuance"]["human_resource_model"])
        self.assertIn("immutable-resource-grant", token["issuance"]["service_account_grant"])

        grants = self.contract["authorization"]["issuer_scope_grants"]
        self.assertEqual(grants["authority"], "nyankoface-server-side-versioned-per-subject-grant-store")
        self.assertEqual(grants["default"], "empty-deny-all")
        self.assertIn("administrator", grants["authentication"])
        self.assertIn("recent-reauthentication", grants["authentication"])
        self.assertEqual(grants["recent_reauthentication"]["maximum_age_seconds"], 300)
        self.assertIn(
            "require-reauthentication-before-grant-store-read-or-mutation",
            grants["recent_reauthentication"]["expired_proof"],
        )
        self.assertIn("requested-token-scopes-never-authoritative", grants["assignment"])
        self.assertIn("old-version-new-version-and-scope-diff", grants["audit"])
        self.assertIn("every-resource-request-before-adapter", grants["enforcement"])
        self.assertIn("reject-token-scopes-outside-current-grant", grants["enforcement"])
        self.assertIn("revoke-all-subject-tokens", grants["reduction_or_revocation"])
        self.assertIn("fail-closed", grants["authority_failure"])
        self.assertIn("version-bound-read-fence", grants["toctou"])
        self.assertIn("immediately-before-adapter-dispatch", grants["toctou"])
        self.assertIn("cannot-return-until-old-version-dispatches-finish", grants["toctou"])
        self.assertIn("nyankoface-local-session", token["issuance"]["human_authentication"])
        self.assertIn("administrator", token["issuance"]["service_account_grant"])
        self.assertEqual(token["recent_reauthentication"]["maximum_age_seconds"], 300)
        self.assertIn("require-reauthentication", token["recent_reauthentication"]["expired_proof"])
        self.assertIn(
            "issuer-scope-grant-administration",
            token["recent_reauthentication"]["expired_proof"],
        )
        self.assertEqual(token["rotation"]["token_ids"], "distinct")
        self.assertEqual(token["rotation"]["maximum_overlap_seconds"], 300)
        self.assertIn("force-revoke", token["rotation"]["overlap_expiry"])
        self.assertIn("immediately", token["rotation"]["early_revocation"])
        self.assertEqual(
            token["stored_metadata"]["service_account_fields"],
            ["resource_grant_id"],
        )
        self.assertEqual(
            token["stored_metadata"]["common_fields"],
            [
                "one_way_digest",
                "token_id",
                "subject_id",
                "audience",
                "scopes",
                "created_at",
                "expires_at",
                "revocation_state",
            ],
        )
        self.assertIn(
            "immutable-exact-resource-grant",
            token["stored_metadata"]["resource_grant_id"],
        )
        self.assertNotIn(
            "resource_grant_id",
            token["stored_metadata"]["common_fields"],
        )

    def test_service_account_resource_grant_bootstrap_and_revocation_are_explicit(self):
        grants = self.contract["authorization"]["service_account_resource_grants"]
        self.assertEqual(
            grants["collection_route"],
            "/api/v1/admin/service-account-resource-grants",
        )
        self.assertEqual(
            grants["item_route"],
            "/api/v1/admin/service-account-resource-grants/{grant_id}",
        )
        self.assertEqual(
            grants["methods"],
            {"create": "POST", "list": "GET", "read": "GET", "revoke": "DELETE"},
        )
        self.assertEqual(grants["recent_reauthentication_maximum_age_seconds"], 300)
        self.assertIn("does-not-require-a-preexisting", grants["bootstrap"])
        self.assertIn("current-forgejo-owner-or-administrator", grants["create_authority"])
        self.assertIn("meet-each-immutable-target-required-permission", grants["dedicated_user_check"])
        self.assertEqual(grants["permission_order"], ["none", "read", "write", "admin"])
        self.assertEqual(grants["allowed_required_permission_values"], ["read", "write"])
        self.assertEqual(
            grants["repository_target_record"],
            {
                "repository_id": "immutable-canonical-forgejo-repository-id",
                "required_permission": "immutable-derived-read-or-write",
            },
        )
        self.assertIn("non-empty-declared-scopes", grants["allowed_scopes_validation"])
        self.assertEqual(grants["client_required_permission_input"], "forbidden-server-derived-only")
        self.assertIn("action_permission_matrix", grants["required_permission_derivation"])
        self.assertIn("immutable-allowed_scopes", grants["required_permission_derivation"])
        self.assertIn("subset-of-immutable-allowed_scopes", grants["token_scope_ceiling"])
        self.assertIn("persists-the-selected-active-resource_grant_id", grants["token_binding"])
        self.assertIn("rotation-preserves-the-token-resource_grant_id", grants["token_binding"])
        self.assertIn("exact-active-grant-current-version", grants["token_binding"])
        self.assertEqual(
            set(grants["immutable_fields"]),
            {
                "grant_id",
                "owner_subject_id",
                "service_account_subject_id",
                "dedicated_forgejo_user_id",
                "allowed_scopes",
                "repository_targets",
            },
        )
        self.assertIn("immutable-owner-subject", grants["management_authority"])
        self.assertIn("successor-current-nyankoface-administrator", grants["revocation_authority"])
        self.assertIn("fresh-reauthentication", grants["revocation_authority"])
        self.assertIn("former-owner-subject", grants["successor_revocation_audit"])
        self.assertIn("resource_grant_id-exactly-matches", grants["revocation"])
        self.assertIn("before-return", grants["revocation"])
        self.assertIn("prevents-new-adapter-calls", grants["revocation_dispatch_fence"])
        self.assertIn("every-service-account-resource-request", grants["request_enforcement"])
        self.assertIn("token-immutable-resource_grant_id", grants["request_enforcement"])
        self.assertIn("that-exact-grant-current-version", grants["request_enforcement"])
        self.assertIn("each-bound-target-required_permission", grants["request_enforcement"])
        self.assertIn("action_permission_matrix-requirement", grants["request_enforcement"])
        self.assertIn("same-grant-id-and-version", grants["request_enforcement"])
        self.assertIn("holds-fence-through-dispatch", grants["request_enforcement"])
        self.assertIn("never-adopt-or-resolve-to-the-replacement-grant", grants["replacement"])
        self.assertIn("every-create-and-revoke", grants["audit"])
        self.assertIn("fail-closed", grants["authority_failure"])

    def test_required_scopes_are_explicit(self):
        required = {
            "repos:read", "repos:write", "issues:read", "issues:write",
            "spaces:read", "spaces:run", "secrets:read-metadata", "secrets:write",
            "pipelines:read", "pipelines:write", "metrics:read", "reactions:write",
        }
        self.assertEqual(set(self.contract["scopes"]), required)

    def test_action_permission_matrix_is_complete_and_unambiguous(self):
        scope_actions = set(self.contract["action_scope_matrix"])
        permission_matrix = self.contract["action_permission_matrix"]
        self.assertEqual(set(permission_matrix), scope_actions)
        self.assertEqual(
            permission_matrix,
            {
                "repos.read": "read",
                "repos.write": "write",
                "issues.read": "read",
                "issues.write": "write",
                "spaces.status": "read",
                "spaces.run": "write",
                "spaces.environment-metadata": "read",
                "spaces.secret-write": "write",
                "pipelines.read": "read",
                "pipelines.write": "write",
                "metrics.read": "read",
                "reactions.write": "write",
            },
        )

    def test_secret_plaintext_is_write_only_and_forbidden_in_responses(self):
        secrets = self.contract["secrets"]
        self.assertTrue(secrets["plaintext_write_only"])
        self.assertIn("value", secrets["response_forbidden_fields"])
        self.assertNotIn("value", secrets["response_allowed_fields"])
        self.assertGreaterEqual(
            set(secrets["redact_from"]), {"logs", "errors", "audit", "traces", "metrics"}
        )

    def test_authorization_never_inherits_service_pat_power(self):
        auth = self.contract["authorization"]
        self.assertEqual(auth["repository_check"], "every-request")
        self.assertTrue(auth["deny_on_mapping_failure"])
        self.assertEqual(
            auth["service_credentials"], "never-authoritative-for-caller-permission"
        )
        self.assertIn("dedicated-forgejo-user", auth["subject_mapping"])
        self.assertIn("explicit", auth["service_account_repository_authority"])
        self.assertIn("immutable-nyankoface-resource-grant", auth["service_account_repository_authority"])
        self.assertIn("fail-closed", auth["repository_authority_failure"])
        self.assertEqual(auth["positive_permission_cache"], "forbidden")
        token_management = auth["token_management"]
        self.assertFalse(token_management["bearer_token_allowed"])
        self.assertIn("recent-reauthentication", token_management["authentication"])
        self.assertIn("none-at-issuance-or-rotation", token_management["human_resource_permission_check"])
        self.assertIn(
            "current-dedicated-forgejo-user-level",
            token_management["service_account_resource_permission_check"],
        )
        self.assertIn(
            "every-immutable-target-required_permission",
            token_management["service_account_resource_permission_check"],
        )
        self.assertIn(
            "immutable-resource_grant_id",
            token_management["service_account_resource_permission_check"],
        )
        self.assertIn(
            "exact-current-grant-version",
            token_management["service_account_resource_permission_check"],
        )
        self.assertIn("current-nyankoface-administrator", token_management["service_account_management_authority"])
        self.assertEqual(
            set(token_management["actions"]),
            {"tokens.issue", "tokens.list", "tokens.rotate", "tokens.revoke"},
        )

    def test_action_scope_matrix_covers_every_public_family(self):
        matrix = self.contract["action_scope_matrix"]
        expected_actions = {
            "repos.read", "repos.write", "issues.read", "issues.write",
            "spaces.status", "spaces.run", "spaces.environment-metadata",
            "spaces.secret-write", "pipelines.read", "pipelines.write",
            "metrics.read", "reactions.write",
        }
        self.assertEqual(set(matrix), expected_actions)
        declared_scopes = set(self.contract["scopes"])
        self.assertTrue(all(set(scopes) <= declared_scopes for scopes in matrix.values()))
        self.assertTrue(all(scopes for scopes in matrix.values()))

    def test_replay_and_rate_limit_controls_are_deterministic(self):
        self.assertEqual(
            self.contract["idempotency"]["namespace_fields"],
            ["verified_subject_id", "http_method", "canonical_target", "idempotency_key"],
        )
        self.assertEqual(
            self.contract["idempotency"]["payload_fingerprint_role"],
            "mismatch-detection-within-namespace-only",
        )
        self.assertEqual(
            self.contract["idempotency"]["same_key_same_payload"],
            "replay-original-response-without-second-mutation-except-non-replayable-credential-responses",
        )
        credential_replay = self.contract["idempotency"]["non_replayable_credential_responses"]
        self.assertEqual(set(credential_replay["routes"]), {"tokens.issue", "tokens.rotate"})
        self.assertIn("never-persisted", credential_replay["plaintext_delivery"])
        self.assertEqual(
            credential_replay["successful_initial_response_headers"],
            {"Cache-Control": "no-store"},
        )
        self.assertEqual(credential_replay["same_key_retry_status"], 409)
        self.assertEqual(credential_replay["same_key_retry_code"], "idempotency_result_not_replayable")
        requirements = {
            item["id"]: item["assertion"]
            for item in self.contract["security_requirements"]
        }
        self.assertIn("Except for the non-replayable", requirements["SEC-007"])
        self.assertIn("Cache-Control: no-store", requirements["SEC-023"])
        self.assertIn("scope-only global credentials", requirements["SEC-024"])
        self.assertIn("every resource request", requirements["SEC-024"])
        self.assertIn("immutable explicit resource grant", requirements["SEC-024"])
        self.assertIn("required_permission", requirements["SEC-024"])
        self.assertIn("action_permission_matrix", requirements["SEC-024"])
        self.assertIn("DELETE", self.contract["idempotency"]["required_for"])
        self.assertEqual(self.contract["idempotency"]["same_key_different_payload_status"], 422)
        self.assertEqual(self.contract["idempotency"]["concurrent_duplicate_status"], 409)
        self.assertEqual(self.contract["controls"]["cors_default"], "deny")
        self.assertFalse(self.contract["controls"]["cors_wildcard_with_credentials"])

    def test_bearer_challenges_follow_rfc_6750(self):
        challenge = self.contract["error"]["bearer_challenge"]
        self.assertEqual(challenge["header"], "WWW-Authenticate")
        self.assertEqual(challenge["scheme"], "Bearer")
        self.assertEqual(
            challenge["missing_credentials"],
            {
                "status": 401,
                "include_error": False,
                "when": "pre-authentication-rate-limit-admits-request",
            },
        )
        self.assertEqual(
            challenge["invalid_token"],
            {
                "status": 401,
                "error": "invalid_token",
                "when": "pre-authentication-rate-limit-admits-request",
            },
        )
        self.assertEqual(
            challenge["unsupported_authorization_scheme"],
            {
                "status": 401,
                "include_error": False,
                "when": "pre-authentication-rate-limit-admits-request",
            },
        )
        self.assertEqual(challenge["insufficient_scope"]["status"], 403)
        self.assertEqual(challenge["insufficient_scope"]["error"], "insufficient_scope")
        self.assertTrue(challenge["insufficient_scope"]["include_scope"])
        self.assertEqual(
            challenge["insufficient_scope"]["when"],
            "pre-authentication-and-post-authentication-rate-limits-admit-request",
        )

    def test_authentication_status_requirements_preserve_rate_limit_precedence(self):
        requirements = {
            item["id"]: item["assertion"] for item in self.contract["security_requirements"]
        }
        self.assertIn("pre-authentication rate limit admits", requirements["SEC-001"])
        self.assertIn(
            "pre-authentication and post-authentication rate limits admit",
            requirements["SEC-002"],
        )
        self.assertIn("pre-authentication rate limit admits", requirements["SEC-018"])

    def test_denial_audit_and_browser_exchange_controls_are_explicit(self):
        controls = self.contract["controls"]
        self.assertGreaterEqual(
            set(controls["audit_required_for"]),
            {"authentication-denial", "authorization-denial", "rate-limit-denial", "mutation"},
        )
        self.assertNotIn("token", controls["audit_unknown_bearer_context"])
        self.assertGreaterEqual(
            set(controls["audit_unknown_bearer_context"]),
            {"request_id", "target", "operation", "result", "time", "credential_present"},
        )
        self.assertIn("repeat-rate-limit-denials", controls["audit_denial_order"])
        rate_audit = controls["rate_limit_denial_audit"]
        self.assertEqual(rate_audit["mode"], "bounded-fixed-window-aggregation")
        self.assertIn("deployment-wide", rate_audit["scope"])
        self.assertEqual(rate_audit["authority"], "shared-authoritative-store")
        self.assertIn("claim-first-rejection", rate_audit["atomic_operations"])
        self.assertEqual(rate_audit["window_seconds"], 60)
        self.assertEqual(
            rate_audit["window_alignment"],
            "unix-epoch-aligned-non-overlapping-windows",
        )
        self.assertEqual(
            rate_audit["key_fields"],
            ["limiter_stage", "source_address_class", "route_class", "fixed_window"],
        )
        self.assertIn("without-per-request-audit-write", rate_audit["repeat_rejection"])
        self.assertIn("shared-authoritative", rate_audit["repeat_rejection"])
        self.assertIn("60-second-window-closes", rate_audit["summary"])
        self.assertIn("immediately-previous-window-only", rate_audit["state_retention"])
        self.assertEqual(rate_audit["maximum_keys_per_window"], 4096)
        self.assertIn("global-per-deployment", rate_audit["maximum_keys_scope"])
        self.assertIn("overflow-summary", rate_audit["overflow"])
        self.assertEqual(rate_audit["raw_credential_or_address"], "forbidden")
        exchange = controls["browser_session_exchange"]
        self.assertTrue(exchange["server_side_only"])
        self.assertGreaterEqual(
            set(exchange["cookie_attributes"]), {"Secure", "HttpOnly", "SameSite"}
        )
        self.assertIn("csrf", exchange["csrf"])

    def test_rate_limit_and_standards_reference_topics_are_traceable(self):
        keys = self.contract["controls"]["rate_limit_keys"]
        self.assertEqual(keys["bearer_routes"]["pre_auth"], ["source_address_class", "route_class"])
        self.assertEqual(keys["bearer_routes"]["post_auth"], ["verified_token_id", "route_class"])
        session_keys = keys["session_managed_token_routes"]
        self.assertEqual(
            session_keys["pre_auth"],
            ["source_address_class", "route_class"],
        )
        self.assertEqual(
            session_keys["post_auth"],
            ["verified_local_session_subject_id", "route_class", "source_address_class"],
        )
        token_management = self.contract["authorization"]["token_management"]
        self.assertIn("local-server-side-session", token_management["session_authority"])
        self.assertIn(
            "session-subject-only-before-post-auth-rate-limit",
            token_management["session_validation"],
        )
        self.assertIn(
            "after-post-auth-rate-limit",
            token_management["recent_reauthentication_proof"],
        )
        order = self.contract["controls"]["rate_limit_order"]
        self.assertEqual(
            order["bearer_routes"],
            [
                "pre-auth-before-digest-lookup-denial-audit-and-any-upstream-or-service-adapter-call",
                "post-auth-after-token-validation-before-scope-evaluation-denial-audit-and-any-upstream-or-service-adapter-call",
            ],
        )
        self.assertEqual(
            order["session_managed_token_routes"],
            [
                "pre-auth-before-local-session-validation-and-any-upstream-or-service-adapter-call",
                "post-auth-after-local-session-subject-validation-before-recent-reauthentication-token-store-or-any-upstream-or-service-adapter-call",
            ],
        )
        self.assertEqual(
            self.contract["controls"]["rate_limit_keys"][
                "session_managed_scope_grant_admin_routes"
            ],
            {
                "routes": ["/api/v1/admin/subjects/{subject_id}/scope-grants"],
                "pre_auth": ["source_address_class", "route_class"],
                "post_auth": [
                    "verified_local_session_subject_id",
                    "route_class",
                    "source_address_class",
                ],
            },
        )
        self.assertEqual(
            order["session_managed_scope_grant_admin_routes"],
            [
                "pre-auth-before-local-session-validation-denial-audit-grant-store-read-and-any-upstream-or-service-adapter-call",
                "post-auth-after-local-session-validation-before-admin-authorization-recent-reauthentication-grant-store-access-or-any-upstream-or-service-adapter-call",
            ],
        )
        resource_grant_keys = keys["session_managed_resource_grant_admin_routes"]
        self.assertEqual(
            resource_grant_keys["routes"],
            [
                "/api/v1/admin/service-account-resource-grants",
                "/api/v1/admin/service-account-resource-grants/{grant_id}",
            ],
        )
        self.assertEqual(
            order["session_managed_resource_grant_admin_routes"],
            [
                "pre-auth-before-local-session-validation-denial-audit-resource-grant-store-read-and-any-upstream-or-service-adapter-call",
                "post-auth-after-local-session-validation-before-admin-authorization-recent-reauthentication-resource-grant-store-access-or-any-upstream-or-service-adapter-call",
            ],
        )
        policies = self.contract["controls"]["rate_limit_policies"]
        self.assertEqual(
            policies["algorithm"],
            "deployment-wide-atomic-fixed-window-plus-token-bucket",
        )
        expected_policies = {
            "bearer_routes": ((60, 10, 1), (600, 50, 10)),
            "session_managed_token_routes": ((30, 5, 0.5), (120, 10, 2)),
            "session_managed_scope_grant_admin_routes": (
                (20, 5, 0.333333),
                (30, 5, 0.5),
            ),
            "session_managed_resource_grant_admin_routes": (
                (20, 5, 0.333333),
                (30, 5, 0.5),
            ),
        }
        for route_class, (pre_expected, post_expected) in expected_policies.items():
            for stage, expected in (("pre_auth", pre_expected), ("post_auth", post_expected)):
                policy = policies[route_class][stage]
                self.assertEqual(policy["window_seconds"], 60)
                self.assertEqual(
                    (
                        policy["requests_per_window"],
                        policy["burst_capacity"],
                        policy["burst_refill_tokens_per_second"],
                    ),
                    expected,
                )
        coordination = self.contract["controls"]["rate_limit_coordination"]
        self.assertIn("all-api-workers", coordination["scope"])
        self.assertEqual(coordination["authority"], "shared-authoritative-store")
        self.assertIn("atomic", coordination["operation"])
        self.assertEqual(coordination["clock"], "authoritative-store-time")
        self.assertIn("fail-closed", coordination["authority_failure"])
        self.assertEqual(
            self.contract["controls"]["session_pre_auth_coverage"],
            ["missing-session", "invalid-session", "valid-session"],
        )
        self.assertEqual(
            self.contract["controls"]["scope_grant_admin_pre_auth_coverage"],
            ["missing-session", "invalid-session", "valid-session"],
        )
        self.assertEqual(
            self.contract["controls"]["resource_grant_admin_pre_auth_coverage"],
            ["missing-session", "invalid-session", "valid-session"],
        )
        self.assertEqual(
            self.contract["controls"]["bearer_pre_auth_coverage"],
            [
                "missing-credentials",
                "unsupported-authorization-scheme",
                "malformed-or-unknown-token",
                "valid-token",
            ],
        )
        self.assertEqual(
            self.contract["controls"]["rate_limit_headers"],
            ["RateLimit", "RateLimit-Policy", "Retry-After"],
        )
        topics = {reference["topic"] for reference in self.contract["standards"]}
        self.assertGreaterEqual(
            topics,
            {"bearer", "revocation", "problem-details", "sunset", "cors", "openapi", "structured-fields", "idempotency", "rate-limit"},
        )
        references = {item["topic"]: item for item in self.contract["standards"]}
        self.assertEqual(references["structured-fields"]["url"], "https://www.rfc-editor.org/rfc/rfc9651.html")
        self.assertIn("syntax foundation", references["structured-fields"]["status"])
        self.assertEqual(
            references["rate-limit"]["url"],
            "https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-ratelimit-headers-11",
        )
        self.assertIn("active IETF draft", references["rate-limit"]["status"])

    def test_all_security_requirements_have_unique_stable_ids(self):
        requirements = self.contract["security_requirements"]
        ids = [item["id"] for item in requirements]
        self.assertEqual(ids, [f"SEC-{number:03d}" for number in range(1, 27)])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(item["assertion"].endswith(".") for item in requirements))

    def test_git_data_plane_stays_native(self):
        native = set(self.contract["native_forgejo_data_plane"])
        self.assertGreaterEqual(native, {"git-https-clone-push", "git-ssh-clone-push", "git-lfs"})


if __name__ == "__main__":
    unittest.main()
