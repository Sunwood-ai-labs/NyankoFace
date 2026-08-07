"""Forgejo Actions-backed CI/CD control plane for NyankoFace repositories."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from contextlib import contextmanager
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

import httpx
import psycopg
from psycopg import sql
from psycopg.rows import dict_row

import config
import forgejo
import preview_artifacts
import space_environment

PIPELINE_WORKFLOW_PATH = ".forgejo/workflows/nyankoface-pipeline.yml"
PIPELINE_ENVIRONMENTS = ("preview", "staging", "production")
PIPELINE_RUNNER_TARGETS = ("node20", "gpu")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_LOG_LINE = re.compile(r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\S+Z)\s?(?P<message>.*)$")
_RUNNER_LINE = re.compile(
    r"^(?P<name>[^\s(]+)\(version:(?P<version>[^)]+)\)\s+received task\b"
)
MAX_JOB_LOG_LINES = 2_000
MAX_JOB_LOG_TAIL_BYTES = 4 * 1024 * 1024
MAX_JOB_LOG_LINE_BYTES = 64 * 1024
MAX_JOB_LOG_STEPS = 256
MAX_JOB_LOG_STEP_SUMMARY_CHARS = 1_024
JOB_LOG_CHUNK_BYTES = 64 * 1024
PIPELINE_SCHEMA_VERSION = 1
logger = logging.getLogger("spaces-runner.pipeline-control")

STARTER_WORKFLOW = r"""name: NyankoFace CI/CD
run-name: NyankoFace ${{ inputs.environment || github.event_name }} · ${{ github.ref_name }}

on:
  push:
    branches:
      - "**"
    tags:
      - "v*"
  pull_request:
    types:
      - opened
      - synchronize
      - reopened
      - closed
  release:
    types:
      - published
  schedule:
    - cron: "17 3 * * 1"
  workflow_dispatch:
    inputs:
      environment:
        description: Deployment environment
        required: true
        type: choice
        default: staging
        options:
          - preview
          - staging
          - production
      revision:
        description: Optional revision to deploy or roll back to
        required: false
        type: string
      delay_seconds:
        description: Optional validation delay for cancellation drills (0-120)
        required: false
        type: string
        default: "0"
      approve_production:
        description: Confirm a manually dispatched production deployment
        required: false
        type: choice
        default: "false"
        options:
          - "false"
          - "true"
      runner:
        description: Runner capability
        required: false
        type: choice
        default: node20
        options:
          - node20
          - gpu

permissions:
  contents: read

concurrency:
  group: >-
    nyankoface-${{ github.workflow }}-${{
      (
        (github.event_name == 'push' &&
         github.ref_name == github.event.repository.default_branch) ||
        github.event_name == 'release' ||
        startsWith(github.ref, 'refs/tags/') ||
        (github.event_name == 'workflow_dispatch' &&
         inputs.environment == 'production' &&
         inputs.approve_production == 'true')
      ) && 'production' ||
      (inputs.environment == 'staging' && 'staging') ||
      format('{0}-{1}', inputs.environment || github.event_name, github.ref)
    }}
  cancel-in-progress: ${{ !((
    github.event_name == 'push' &&
    github.ref_name == github.event.repository.default_branch
    ) || github.event_name == 'release' ||
    startsWith(github.ref, 'refs/tags/') ||
    (github.event_name == 'workflow_dispatch' &&
     inputs.environment == 'production' &&
     inputs.approve_production == 'true')) }}

jobs:
  validate:
    name: Build and test
    if: github.event_name != 'pull_request' || github.event.action != 'closed'
    runs-on: ${{ inputs.runner || 'node20' }}
    timeout-minutes: 20
    outputs:
      revision: ${{ steps.revision.outputs.sha }}
    steps:
      - name: Check out repository
        uses: https://data.forgejo.org/actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          ref: ${{ inputs.revision || github.sha }}
          persist-credentials: false
      - name: Resolve immutable revision
        id: revision
        shell: bash
        run: |
          set -euo pipefail
          RESOLVED_REVISION="$(git rev-parse HEAD)"
          test -n "${RESOLVED_REVISION}"
          echo "sha=${RESOLVED_REVISION}" >> "${GITHUB_OUTPUT}"
      - name: Restore dependency cache
        uses: https://data.forgejo.org/actions/cache@5a3ec84eff668545956fd18022155c47e93e2684 # v4.2.3
        with:
          path: |
            ~/.npm
            ~/.cache/pip
          key: nyankoface-${{ runner.os }}-${{ hashFiles('**/package-lock.json', '**/requirements*.txt', '**/pyproject.toml') }}
      - name: Apply optional cancellation-drill delay
        env:
          DELAY_SECONDS: ${{ inputs.delay_seconds || '0' }}
        shell: bash
        run: |
          set -euo pipefail
          case "$DELAY_SECONDS" in
            ''|*[!0-9]*) echo "delay_seconds must be an integer" >&2; exit 2 ;;
          esac
          test "$DELAY_SECONDS" -le 120
          sleep "$DELAY_SECONDS"
      - name: Validate project
        shell: bash
        run: |
          set -euo pipefail
          if [ -f package.json ]; then
            npm install --no-audit --no-fund
            npm test --if-present
            npm run lint --if-present
            if node -e "const s=require('./package.json').scripts||{};process.exit(s['docs:build']?0:1)"; then
              npm run docs:build
            else
              npm run build --if-present
            fi
          fi
          if find . -maxdepth 3 -name '*.py' -print -quit | grep -q .; then
            python3 -m compileall -q .
          fi
      - name: Dependency security audit
        shell: bash
        run: |
          set -euo pipefail
          if [ -f package-lock.json ]; then
            npm audit --omit=dev --audit-level=high
          fi

  preview:
    name: Publish preview site
    if: >
      (github.event_name == 'pull_request' && github.event.action != 'closed') ||
      (github.event_name == 'workflow_dispatch' && inputs.environment == 'preview')
    needs: validate
    runs-on: ${{ inputs.runner || 'node20' }}
    timeout-minutes: 10
    steps:
      - name: Check out repository
        uses: https://data.forgejo.org/actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          ref: ${{ needs.validate.outputs.revision }}
      - name: Prepare preview output
        id: pages
        shell: bash
        run: |
          set -euo pipefail
          rm -rf /tmp/nyankoface-preview
          mkdir -p /tmp/nyankoface-preview .nyankoface-artifacts
          SOURCE_SHA="$(git rev-parse HEAD)"
          if [ -f package.json ]; then
            npm install --no-audit --no-fund
            if node -e "const s=require('./package.json').scripts||{};process.exit(s['docs:build']?0:1)"; then
              PREVIEW_KEY="run-${GITHUB_RUN_NUMBER}"
              if [ "${GITHUB_EVENT_NAME}" = "pull_request" ]; then
                PR_NUMBER="$(node -p "require(process.env.GITHUB_EVENT_PATH).pull_request.number")"
                PREVIEW_KEY="pr-${PR_NUMBER}"
              fi
              VITEPRESS_BASE="/previews/${GITHUB_REPOSITORY}/${PREVIEW_KEY}/" npm run docs:build
            else
              npm run build --if-present
            fi
          fi
          if [ -d docs/.vitepress/dist ]; then
            cp -R docs/.vitepress/dist/. /tmp/nyankoface-preview/
          elif [ -d dist ] && [ -f dist/index.html ]; then
            cp -R dist/. /tmp/nyankoface-preview/
          elif [ -f docs/index.html ]; then
            cp -R docs/. /tmp/nyankoface-preview/
          elif [ -f index.html ]; then
            cp -R . /tmp/nyankoface-preview/
            rm -rf \
              /tmp/nyankoface-preview/.git \
              /tmp/nyankoface-preview/.forgejo \
              /tmp/nyankoface-preview/.github \
              /tmp/nyankoface-preview/node_modules
          else
            echo "No Pages output detected; preview URL is not required."
            printf '%s\n' \
              "{\"schema\":1,\"repository\":\"${GITHUB_REPOSITORY}\",\"sha\":\"${SOURCE_SHA}\",\"run_id\":\"${GITHUB_RUN_ID}\",\"run_number\":\"${GITHUB_RUN_NUMBER}\",\"event\":\"${GITHUB_EVENT_NAME}\",\"environment\":\"preview\",\"operation\":\"delete\"}" \
              > .nyankoface-artifacts/nyankoface-site-manifest.json
            echo "enabled=false" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          test -f /tmp/nyankoface-preview/index.html
          tar -C /tmp/nyankoface-preview -czf .nyankoface-artifacts/nyankoface-site.tgz .
          ARTIFACT_SHA256="$(sha256sum .nyankoface-artifacts/nyankoface-site.tgz | cut -d' ' -f1)"
          printf '%s\n' \
            "{\"schema\":1,\"repository\":\"${GITHUB_REPOSITORY}\",\"sha\":\"${SOURCE_SHA}\",\"run_id\":\"${GITHUB_RUN_ID}\",\"run_number\":\"${GITHUB_RUN_NUMBER}\",\"event\":\"${GITHUB_EVENT_NAME}\",\"environment\":\"preview\",\"operation\":\"publish\",\"artifact\":\"nyankoface-site.tgz\",\"artifact_sha256\":\"${ARTIFACT_SHA256}\"}" \
            > .nyankoface-artifacts/nyankoface-site-manifest.json
          echo "enabled=true" >> "$GITHUB_OUTPUT"
      - name: Upload preview artifact
        uses: https://data.forgejo.org/actions/upload-artifact@a8a3f3ad30e3422c9c7b888a15615d19a852ae32 # v3.1.3
        with:
          name: nyankoface-preview-site-${{ needs.validate.outputs.revision }}
          path: .nyankoface-artifacts/
          retention-days: 7

  staging:
    name: Publish staging site
    if: github.event_name == 'workflow_dispatch' && inputs.environment == 'staging'
    needs: validate
    runs-on: ${{ inputs.runner || 'node20' }}
    environment: staging
    timeout-minutes: 10
    steps:
      - name: Check out repository
        uses: https://data.forgejo.org/actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          ref: ${{ needs.validate.outputs.revision }}
      - name: Prepare staging output
        id: pages
        shell: bash
        run: |
          set -euo pipefail
          rm -rf /tmp/nyankoface-staging
          mkdir -p /tmp/nyankoface-staging .nyankoface-artifacts
          if [ -f package.json ]; then
            npm install --no-audit --no-fund
            if node -e "const s=require('./package.json').scripts||{};process.exit(s['docs:build']?0:1)"; then
              VITEPRESS_BASE="/staging/${GITHUB_REPOSITORY}/" npm run docs:build
            else
              npm run build --if-present
            fi
          fi
          if [ -d docs/.vitepress/dist ]; then
            cp -R docs/.vitepress/dist/. /tmp/nyankoface-staging/
          elif [ -d dist ] && [ -f dist/index.html ]; then
            cp -R dist/. /tmp/nyankoface-staging/
          elif [ -f docs/index.html ]; then
            cp -R docs/. /tmp/nyankoface-staging/
          elif [ -f index.html ]; then
            cp -R . /tmp/nyankoface-staging/
            rm -rf \
              /tmp/nyankoface-staging/.git \
              /tmp/nyankoface-staging/.forgejo \
              /tmp/nyankoface-staging/.github \
              /tmp/nyankoface-staging/node_modules
          else
            echo "No Pages output detected; staging URL is not required."
            SOURCE_SHA="$(git rev-parse HEAD)"
            printf '%s\n' \
              "{\"schema\":1,\"repository\":\"${GITHUB_REPOSITORY}\",\"sha\":\"${SOURCE_SHA}\",\"run_id\":\"${GITHUB_RUN_ID}\",\"run_number\":\"${GITHUB_RUN_NUMBER}\",\"event\":\"${GITHUB_EVENT_NAME}\",\"environment\":\"staging\",\"operation\":\"delete\"}" \
              > .nyankoface-artifacts/nyankoface-site-manifest.json
            echo "enabled=false" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          test -f /tmp/nyankoface-staging/index.html
          tar -C /tmp/nyankoface-staging -czf .nyankoface-artifacts/nyankoface-site.tgz .
          ARTIFACT_SHA256="$(sha256sum .nyankoface-artifacts/nyankoface-site.tgz | cut -d' ' -f1)"
          SOURCE_SHA="$(git rev-parse HEAD)"
          printf '%s\n' \
            "{\"schema\":1,\"repository\":\"${GITHUB_REPOSITORY}\",\"sha\":\"${SOURCE_SHA}\",\"run_id\":\"${GITHUB_RUN_ID}\",\"run_number\":\"${GITHUB_RUN_NUMBER}\",\"event\":\"${GITHUB_EVENT_NAME}\",\"environment\":\"staging\",\"operation\":\"publish\",\"artifact\":\"nyankoface-site.tgz\",\"artifact_sha256\":\"${ARTIFACT_SHA256}\"}" \
            > .nyankoface-artifacts/nyankoface-site-manifest.json
          echo "enabled=true" >> "$GITHUB_OUTPUT"
      - name: Upload staging artifact
        uses: https://data.forgejo.org/actions/upload-artifact@a8a3f3ad30e3422c9c7b888a15615d19a852ae32 # v3.1.3
        with:
          name: nyankoface-staging-site-${{ needs.validate.outputs.revision }}
          path: .nyankoface-artifacts/
          retention-days: 7

  production:
    name: Publish production Pages
    if: >
      (github.event_name == 'push' &&
       github.ref_name == github.event.repository.default_branch) ||
      github.event_name == 'release' ||
      startsWith(github.ref, 'refs/tags/') ||
      (github.event_name == 'workflow_dispatch' &&
       inputs.environment == 'production' &&
       inputs.approve_production == 'true')
    needs: validate
    runs-on: ${{ inputs.runner || 'node20' }}
    permissions:
      contents: write
    environment: production
    timeout-minutes: 15
    steps:
      - name: Check out repository
        uses: https://data.forgejo.org/actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          ref: ${{ needs.validate.outputs.revision }}
      - name: Record immutable production revision
        id: deployed
        shell: bash
        run: |
          set -euo pipefail
          DEPLOY_REVISION="$(git rev-parse HEAD)"
          test -n "${DEPLOY_REVISION}"
          echo "sha=${DEPLOY_REVISION}" >> "${GITHUB_OUTPUT}"
          printf '%s\n' "${DEPLOY_REVISION}" > /tmp/nyankoface-production-revision
      - name: Upload immutable production revision
        uses: https://data.forgejo.org/actions/upload-artifact@a8a3f3ad30e3422c9c7b888a15615d19a852ae32 # v4.6.2
        with:
          name: nyankoface-production-revision-${{ steps.deployed.outputs.sha }}
          path: /tmp/nyankoface-production-revision
          retention-days: 90
      - name: Prepare Pages output
        id: pages
        shell: bash
        run: |
          set -euo pipefail
          rm -rf /tmp/nyankoface-pages
          mkdir -p /tmp/nyankoface-pages
          if [ -f package.json ]; then
            npm install --no-audit --no-fund
            if node -e "const s=require('./package.json').scripts||{};process.exit(s['docs:build']?0:1)"; then
              VITEPRESS_BASE="/pages/${GITHUB_REPOSITORY}/" npm run docs:build
            else
              npm run build --if-present
            fi
          fi
          if [ -d docs/.vitepress/dist ]; then
            cp -R docs/.vitepress/dist/. /tmp/nyankoface-pages/
          elif [ -d dist ] && [ -f dist/index.html ]; then
            cp -R dist/. /tmp/nyankoface-pages/
          elif [ -f docs/index.html ]; then
            cp -R docs/. /tmp/nyankoface-pages/
          elif [ -f index.html ]; then
            cp -R . /tmp/nyankoface-pages/
            rm -rf \
              /tmp/nyankoface-pages/.git \
              /tmp/nyankoface-pages/.forgejo \
              /tmp/nyankoface-pages/.github \
              /tmp/nyankoface-pages/node_modules
          else
            echo "No Pages output detected; disabling the previous Pages publication."
            echo "enabled=false" >> "$GITHUB_OUTPUT"
            exit 0
          fi
          test -f /tmp/nyankoface-pages/index.html
          echo "enabled=true" >> "$GITHUB_OUTPUT"
      - name: Reconcile gh-pages
        env:
          PAGES_TOKEN: ${{ github.token }}
          PAGES_ENABLED: ${{ steps.pages.outputs.enabled }}
          DEPLOY_REVISION: ${{ steps.deployed.outputs.sha }}
        shell: bash
        run: |
          set -euo pipefail
          git config user.name "NyankoFace Pipeline"
          git config user.email "pipeline@nyankoface.local"
          git checkout --orphan gh-pages
          git rm -rf .
          git clean -fdx
          if [ "$PAGES_ENABLED" = "true" ]; then
            cp -R /tmp/nyankoface-pages/. .
            touch .nojekyll
            COMMIT_MESSAGE="Deploy ${DEPLOY_REVISION} to production"
          else
            printf '%s\n' \
              "{\"schema\":1,\"repository\":\"${GITHUB_REPOSITORY}\",\"sha\":\"${DEPLOY_REVISION}\",\"run_id\":\"${GITHUB_RUN_ID}\",\"run_number\":\"${GITHUB_RUN_NUMBER}\",\"event\":\"${GITHUB_EVENT_NAME}\",\"environment\":\"production\",\"operation\":\"delete\"}" \
              > .nyankoface-pages-tombstone.json
            COMMIT_MESSAGE="Disable Pages for ${DEPLOY_REVISION}"
          fi
          git add --all
          git commit -m "$COMMIT_MESSAGE"
          git remote set-url origin "http://oauth2:${PAGES_TOKEN}@forgejo:3000/${GITHUB_REPOSITORY}.git"
          git push --force origin gh-pages

  space:
    name: Restart production Space
    if: >
      (github.event_name == 'push' &&
       github.ref_name == github.event.repository.default_branch) ||
      github.event_name == 'release' ||
      startsWith(github.ref, 'refs/tags/') ||
      (github.event_name == 'workflow_dispatch' &&
       inputs.environment == 'production' &&
       inputs.approve_production == 'true')
    needs: validate
    runs-on: ${{ inputs.runner || 'node20' }}
    environment: production
    timeout-minutes: 10
    steps:
      - name: Check out repository
        uses: https://data.forgejo.org/actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          ref: ${{ needs.validate.outputs.revision }}
      - name: Restart Space when deployment credentials are configured
        env:
          NYANKOFACE_BASE_URL: ${{ vars.NYANKOFACE_BASE_URL }}
          NYANKOFACE_DEPLOY_TOKEN: ${{ secrets.NYANKOFACE_DEPLOY_TOKEN }}
        shell: bash
        run: |
          set -euo pipefail
          if [ ! -f Dockerfile ]; then
            echo "No Dockerfile; Space deployment is not required."
            exit 0
          fi
          if [ -z "${NYANKOFACE_BASE_URL:-}" ] || [ -z "${NYANKOFACE_DEPLOY_TOKEN:-}" ]; then
            echo "Configure NYANKOFACE_BASE_URL and NYANKOFACE_DEPLOY_TOKEN to restart this Space."
            exit 0
          fi
          DEPLOY_REVISION="$(git rev-parse HEAD)"
          test -n "${DEPLOY_REVISION}"
          curl --fail-with-body --silent --show-error \
            --request POST \
            --header "Authorization: Bearer ${NYANKOFACE_DEPLOY_TOKEN}" \
            --header "Content-Type: application/json" \
            --data "{\"restart\":true,\"revision\":\"${DEPLOY_REVISION}\"}" \
            "${NYANKOFACE_BASE_URL%/}/runner-api/v1/spaces/${GITHUB_REPOSITORY}/environment/apply"

  notify:
    name: Notify pipeline webhook
    if: >
      always() &&
      github.event_name != 'pull_request' &&
      vars.NYANKOFACE_PIPELINE_WEBHOOK_URL != ''
    needs:
      - validate
      - preview
      - staging
      - production
      - space
    runs-on: ${{ inputs.runner || 'node20' }}
    timeout-minutes: 5
    steps:
      - name: Check out deployed revision
        uses: https://data.forgejo.org/actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          ref: ${{ needs.validate.outputs.revision }}
          persist-credentials: false
      - name: Send status webhook
        env:
          WEBHOOK_URL: ${{ vars.NYANKOFACE_PIPELINE_WEBHOOK_URL }}
          WEBHOOK_TOKEN: ${{ secrets.NYANKOFACE_PIPELINE_WEBHOOK_TOKEN }}
          VALIDATE_RESULT: ${{ needs.validate.result }}
          PREVIEW_RESULT: ${{ needs.preview.result }}
          STAGING_RESULT: ${{ needs.staging.result }}
          PRODUCTION_RESULT: ${{ needs.production.result }}
          SPACE_RESULT: ${{ needs.space.result }}
        shell: bash
        run: |
          set -euo pipefail
          DEPLOY_REVISION="$(git rev-parse HEAD)"
          test -n "${DEPLOY_REVISION}"
          PIPELINE_STATUS="success"
          case "${VALIDATE_RESULT} ${PREVIEW_RESULT} ${STAGING_RESULT} ${PRODUCTION_RESULT} ${SPACE_RESULT}" in
            *failure*) PIPELINE_STATUS="failure" ;;
            *cancelled*) PIPELINE_STATUS="cancelled" ;;
          esac
          curl --fail-with-body --silent --show-error \
            --request POST \
            --header "Authorization: Bearer ${WEBHOOK_TOKEN}" \
            --header "Content-Type: application/json" \
            --data "{\"repository\":\"${GITHUB_REPOSITORY}\",\"sha\":\"${DEPLOY_REVISION}\",\"run_id\":\"${GITHUB_RUN_ID}\",\"status\":\"${PIPELINE_STATUS}\",\"jobs\":{\"validate\":\"${VALIDATE_RESULT}\",\"preview\":\"${PREVIEW_RESULT}\",\"staging\":\"${STAGING_RESULT}\",\"production\":\"${PRODUCTION_RESULT}\",\"space\":\"${SPACE_RESULT}\"}}" \
            "$WEBHOOK_URL"
"""


class PipelineError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int = 502,
        code: str = "pipeline_error",
        *,
        retry_safe: bool | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        # Validation and lookup failures are known rejections. A 5xx raised
        # after an upstream POST may have committed and must remain locked.
        self.retry_safe = status_code < 500 if retry_safe is None else retry_safe


def _qualified(name: str):
    """Return a safely qualified identifier in the pipeline schema."""
    return sql.SQL("{}.{}").format(
        sql.Identifier(config.PIPELINE_DB_SCHEMA),
        sql.Identifier(name),
    )


def _index(name: str):
    # PostgreSQL resolves an unqualified index name in the table's schema.
    # CREATE INDEX rejects a schema-qualified index name on supported versions.
    return sql.Identifier(name)


def _connect() -> psycopg.Connection:
    """Open one short-lived transaction against the shared metrics database."""
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


@contextmanager
def _transaction(*, retry_safe: bool = True):
    """Run one storage operation and expose only a sanitized service error."""
    try:
        with _connect() as db:
            yield db
    except PipelineError:
        raise
    except (OSError, psycopg.Error) as exc:
        logger.error("pipeline storage operation failed (%s)", type(exc).__name__)
        raise PipelineError(
            "Pipeline persistence is unavailable.",
            status_code=503,
            code="pipeline_storage_unavailable",
            retry_safe=retry_safe,
        ) from exc


def _timestamp_text(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "")


def initialize() -> None:
    """Apply the pipeline schema transactionally and idempotently.

    This is intentionally the only normal-path schema bootstrap.  It never
    looks for or imports the legacy SQLite file; that operation is exposed by
    the explicit ``pipeline_migration`` command.
    """
    with _transaction(retry_safe=False) as db:
        db.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                sql.Identifier(config.PIPELINE_DB_SCHEMA),
            )
        )
        db.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            ).format(_qualified("schema_migrations"))
        )
        current = db.execute(
            sql.SQL(
                "SELECT COALESCE(MAX(version), 0) AS version FROM {}"
            ).format(_qualified("schema_migrations"))
        ).fetchone()
        current_version = int(current["version"] if current else 0)
        if current_version > PIPELINE_SCHEMA_VERSION:
            raise RuntimeError(
                "The pipeline database schema is newer than this runner."
            )

        db.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    owner TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    run_number BIGINT,
                    workflow TEXT,
                    environment TEXT,
                    revision TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            ).format(_qualified("pipeline_audit"))
        )
        db.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    owner TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    run_number BIGINT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('pending', 'watch', 'terminal')),
                    run_id BIGINT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    updated TEXT NOT NULL DEFAULT '',
                    attempt INTEGER NOT NULL CHECK (attempt >= 0),
                    artifact_id BIGINT NOT NULL CHECK (artifact_id >= 0),
                    expires_at TEXT NOT NULL DEFAULT '',
                    revision TEXT,
                    workflow TEXT NOT NULL,
                    checked_at TIMESTAMPTZ NOT NULL,
                    last_audit_id BIGINT NOT NULL,
                    PRIMARY KEY (owner, repo, run_number)
                )
                """
            ).format(_qualified("pipeline_reconcile_state"))
        )
        db.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    owner TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    run_number BIGINT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    last_audit_id BIGINT NOT NULL,
                    PRIMARY KEY (owner, repo)
                )
                """
            ).format(_qualified("pipeline_reconcile_cursor"))
        )
        db.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {} (
                    source_digest TEXT PRIMARY KEY,
                    row_count BIGINT NOT NULL CHECK (row_count >= 0),
                    migrated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            ).format(_qualified("sqlite_migrations"))
        )
        db.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}(owner, repo, id DESC)")
            .format(_index("pipeline_audit_repository_history"), _qualified("pipeline_audit"))
        )
        db.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}(owner, repo, action, run_number, id)"
            ).format(_index("pipeline_audit_reconcile_lookup"), _qualified("pipeline_audit"))
        )
        db.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}(owner, repo, run_number, action, id DESC)"
            ).format(_index("pipeline_audit_production_revision"), _qualified("pipeline_audit"))
        )
        db.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}(owner, repo, state, checked_at, run_number)"
            ).format(_index("pipeline_reconcile_due"), _qualified("pipeline_reconcile_state"))
        )
        db.execute(
            sql.SQL(
                "INSERT INTO {}(version) VALUES(%s) ON CONFLICT(version) DO NOTHING"
            ).format(_qualified("schema_migrations")),
            (PIPELINE_SCHEMA_VERSION,),
        )


def database_ready() -> bool:
    """Return whether the shared DB has the exact pipeline schema version."""
    try:
        with _connect() as db:
            version = db.execute(
                sql.SQL(
                    "SELECT COALESCE(MAX(version), 0) AS version FROM {}"
                ).format(_qualified("schema_migrations"))
            ).fetchone()
            if not version or int(version["version"] or 0) != PIPELINE_SCHEMA_VERSION:
                return False
            for table in (
                "schema_migrations",
                "pipeline_audit",
                "pipeline_reconcile_state",
                "pipeline_reconcile_cursor",
                "sqlite_migrations",
            ):
                present = db.execute(
                    "SELECT to_regclass(%s) AS table_name",
                    (f"{config.PIPELINE_DB_SCHEMA}.{table}",),
                ).fetchone()
                if not present or not present["table_name"]:
                    return False
            for index in (
                "pipeline_audit_repository_history",
                "pipeline_audit_reconcile_lookup",
                "pipeline_audit_production_revision",
                "pipeline_reconcile_due",
            ):
                present = db.execute(
                    "SELECT to_regclass(%s) AS index_name",
                    (f"{config.PIPELINE_DB_SCHEMA}.{index}",),
                ).fetchone()
                if not present or not present["index_name"]:
                    return False
            return True
    except (OSError, psycopg.Error):
        return False


def _insert_audit(
    db: psycopg.Connection,
    owner: str,
    repo: str,
    action: str,
    actor: str,
    *,
    run_number: int | None = None,
    workflow: str | None = None,
    environment: str | None = None,
    revision: str | None = None,
    created_at: datetime | None = None,
) -> int:
    row = db.execute(
        sql.SQL(
            """
            INSERT INTO {}(
                owner, repo, action, actor, run_number, workflow,
                environment, revision, created_at
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """
        ).format(_qualified("pipeline_audit")),
        (
            owner,
            repo,
            action,
            actor,
            run_number,
            workflow,
            environment,
            revision,
            created_at or datetime.now(timezone.utc),
        ),
    ).fetchone()
    if not row:
        raise RuntimeError("The pipeline audit insert did not return an id.")
    return int(row["id"])


def record_event(
    owner: str,
    repo: str,
    action: str,
    actor: str,
    *,
    run_number: int | None = None,
    workflow: str | None = None,
    environment: str | None = None,
    revision: str | None = None,
) -> None:
    initialize()
    with _transaction(retry_safe=False) as db:
        _insert_audit(
            db,
            owner,
            repo,
            action,
            actor,
            run_number=run_number,
            workflow=workflow,
            environment=environment,
            revision=revision,
        )


def list_audit(owner: str, repo: str, limit: int = 100) -> list[dict]:
    initialize()
    with _transaction() as db:
        rows = db.execute(
            sql.SQL(
                """
            SELECT id, action, actor, run_number, workflow, environment,
                   revision, created_at
            FROM {}
            WHERE owner = %s AND repo = %s
              AND action NOT LIKE %s ESCAPE %s
            ORDER BY id DESC
            LIMIT %s
            """
            ).format(_qualified("pipeline_audit")),
            (owner, repo, "\\_reconcile\\_%", "\\", max(1, min(limit, 500))),
        ).fetchall()
    return [
        {
            **dict(row),
            "created_at": _timestamp_text(row["created_at"]),
        }
        for row in rows
    ]


def recorded_production_revision(
    owner: str,
    repo: str,
    run_number: int,
) -> str:
    initialize()
    with _transaction() as db:
        row = db.execute(
            sql.SQL(
                """
            SELECT revision
            FROM {}
            WHERE owner = %s AND repo = %s AND run_number = %s
              AND action = 'deploy_production' AND revision IS NOT NULL
            ORDER BY id DESC
            LIMIT 1
            """
            ).format(_qualified("pipeline_audit")),
            (owner, repo, run_number),
        ).fetchone()
    return str(row["revision"] or "").strip() if row else ""


def _production_run_fingerprint(item: dict) -> str:
    """Identify one Forgejo run attempt, including an in-place rerun update."""
    payload = {
        "id": int(item.get("id") or 0),
        "run_number": int(item.get("index_in_repo") or 0),
        "commit_sha": str(item.get("commit_sha") or ""),
        "status": str(item.get("conclusion") or item.get("status") or ""),
        "started": str(item.get("started") or ""),
        "stopped": str(item.get("stopped") or ""),
        "updated": str(item.get("updated") or item.get("updated_at") or ""),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


_RECONCILE_CURSOR_ACTION = "_reconcile_production_cursor"
_RECONCILE_STATE_ACTION = "_reconcile_production_state"
_PRODUCTION_WATCH_INTERVAL_SECONDS = 60 * 60


def production_reconcile_cursor(owner: str, repo: str) -> int:
    initialize()
    with _transaction() as db:
        row = db.execute(
            sql.SQL(
                """
            SELECT run_number
            FROM {}
            WHERE owner = %s AND repo = %s
            """
            ).format(_qualified("pipeline_reconcile_cursor")),
            (owner, repo),
        ).fetchone()
    return int(row["run_number"] or 0) if row else 0


def _decode_production_state(row: Mapping[str, object] | None) -> dict | None:
    if row is None:
        return None
    try:
        encoded = row["workflow"]
        payload = json.loads(str(encoded))
    except (json.JSONDecodeError, TypeError, KeyError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        payload["run_number"] = int(row["run_number"])
        payload["revision"] = str(row.get("revision") or "")
        payload["checked_at"] = _timestamp_text(row.get("checked_at"))
    except (TypeError, ValueError, KeyError):
        return None
    return payload


def latest_production_reconcile_state(
    owner: str,
    repo: str,
    run_number: int,
) -> dict | None:
    initialize()
    with _transaction() as db:
        row = db.execute(
            sql.SQL(
                """
            SELECT run_number, state, workflow, revision, checked_at
            FROM {}
            WHERE owner = %s AND repo = %s AND run_number = %s
            """
            ).format(_qualified("pipeline_reconcile_state")),
            (owner, repo, run_number),
        ).fetchone()
    return _decode_production_state(row)


def _state_order(state: str) -> int:
    return {"pending": 0, "watch": 1, "terminal": 2}[state]


def _same_state_payload(current: dict, payload: dict, revision: str | None) -> bool:
    return (
        all(current.get(key) == value for key, value in payload.items())
        and str(current.get("revision") or "") == str(revision or "")
    )


def _lock_reconcile_key(db: psycopg.Connection, owner: str, repo: str, run_number: int) -> None:
    db.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))",
        (f"pipeline-reconcile:{owner}/{repo}/{run_number}",),
    )


def _lock_cursor_key(db: psycopg.Connection, owner: str, repo: str) -> None:
    db.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 1))",
        (f"pipeline-cursor:{owner}/{repo}",),
    )


def record_production_reconcile_state(
    owner: str,
    repo: str,
    *,
    run_number: int,
    state: str,
    run_id: int,
    fingerprint: str,
    updated: str = "",
    attempt: int = 0,
    artifact_id: int = 0,
    expires_at: str = "",
    revision: str | None = None,
    force: bool = False,
) -> None:
    if state not in {"pending", "watch", "terminal"}:
        raise ValueError("invalid production reconciliation state")
    payload = {
        "v": 1,
        "state": state,
        "run_id": int(run_id),
        "fingerprint": str(fingerprint),
        "updated": str(updated),
        "attempt": max(0, int(attempt)),
        "artifact_id": max(0, int(artifact_id)),
        "expires_at": str(expires_at),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    revision_value = str(revision or "") or None
    initialize()
    with _transaction(retry_safe=False) as db:
        _lock_reconcile_key(db, owner, repo, run_number)
        current = db.execute(
            sql.SQL(
                """
                SELECT run_number, state, run_id, fingerprint, updated,
                       attempt, artifact_id, expires_at, revision, workflow,
                       checked_at, last_audit_id
                FROM {}
                WHERE owner = %s AND repo = %s AND run_number = %s
                FOR UPDATE
                """
            ).format(_qualified("pipeline_reconcile_state")),
            (owner, repo, run_number),
        ).fetchone()
        current_state = _decode_production_state(current)
        if current and current_state is None:
            raise RuntimeError("The pipeline reconciliation state is invalid.")
        if current_state:
            if _same_state_payload(current_state, payload, revision_value):
                if force:
                    # A forced reconciliation refreshes the due watermark, but
                    # an identical transition must not create a duplicate
                    # audit row when workers race on the same run.
                    checked_at = datetime.now(timezone.utc)
                    db.execute(
                        sql.SQL(
                            """
                            UPDATE {}
                               SET checked_at = %s
                             WHERE owner = %s AND repo = %s AND run_number = %s
                            """
                        ).format(_qualified("pipeline_reconcile_state")),
                        (checked_at, owner, repo, run_number),
                    )
                return
            if not force and current_state.get("fingerprint") == payload["fingerprint"]:
                if _state_order(state) < _state_order(str(current_state.get("state"))):
                    return
            elif not force:
                current_updated = str(current_state.get("updated") or "")
                if current_updated and payload["updated"] and payload["updated"] < current_updated:
                    return

        checked_at = datetime.now(timezone.utc)
        audit_id = _insert_audit(
            db,
            owner,
            repo,
            _RECONCILE_STATE_ACTION,
            "nyankoface-deployer",
            run_number=run_number,
            workflow=encoded,
            environment=state,
            revision=revision_value,
            created_at=checked_at,
        )
        db.execute(
            sql.SQL(
                """
                INSERT INTO {}(
                    owner, repo, run_number, state, run_id, fingerprint,
                    updated, attempt, artifact_id, expires_at, revision,
                    workflow, checked_at, last_audit_id
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(owner, repo, run_number) DO UPDATE SET
                    state = EXCLUDED.state,
                    run_id = EXCLUDED.run_id,
                    fingerprint = EXCLUDED.fingerprint,
                    updated = EXCLUDED.updated,
                    attempt = EXCLUDED.attempt,
                    artifact_id = EXCLUDED.artifact_id,
                    expires_at = EXCLUDED.expires_at,
                    revision = EXCLUDED.revision,
                    workflow = EXCLUDED.workflow,
                    checked_at = EXCLUDED.checked_at,
                    last_audit_id = EXCLUDED.last_audit_id
                """
            ).format(_qualified("pipeline_reconcile_state")),
            (
                owner,
                repo,
                run_number,
                state,
                int(run_id),
                str(fingerprint),
                str(updated),
                max(0, int(attempt)),
                max(0, int(artifact_id)),
                str(expires_at),
                revision_value,
                encoded,
                checked_at,
                audit_id,
            ),
        )


def record_production_reconcile_cursor(
    owner: str,
    repo: str,
    run_number: int,
) -> None:
    if run_number == 0:
        return
    initialize()
    with _transaction(retry_safe=False) as db:
        _lock_cursor_key(db, owner, repo)
        current = db.execute(
            sql.SQL(
                "SELECT run_number FROM {} WHERE owner = %s AND repo = %s FOR UPDATE"
            ).format(_qualified("pipeline_reconcile_cursor")),
            (owner, repo),
        ).fetchone()
        if current and run_number <= int(current["run_number"]):
            return
        now = datetime.now(timezone.utc)
        audit_id = _insert_audit(
            db,
            owner,
            repo,
            _RECONCILE_CURSOR_ACTION,
            "nyankoface-deployer",
            run_number=run_number,
            workflow="v1",
            environment="production",
            created_at=now,
        )
        db.execute(
            sql.SQL(
                """
                INSERT INTO {}(owner, repo, run_number, updated_at, last_audit_id)
                VALUES(%s,%s,%s,%s,%s)
                ON CONFLICT(owner, repo) DO UPDATE SET
                    run_number = EXCLUDED.run_number,
                    updated_at = EXCLUDED.updated_at,
                    last_audit_id = EXCLUDED.last_audit_id
                """
            ).format(_qualified("pipeline_reconcile_cursor")),
            (owner, repo, run_number, now, audit_id),
        )


def due_production_reconcile_states(
    owner: str,
    repo: str,
    limit: int,
) -> list[dict]:
    """Return a fair, fixed-size batch of unresolved production runs."""
    initialize()
    watch_before = datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() - _PRODUCTION_WATCH_INTERVAL_SECONDS,
        tz=timezone.utc,
    )
    with _transaction() as db:
        rows = db.execute(
            sql.SQL(
                """
                SELECT run_number, state, workflow, revision, checked_at
                FROM {}
                WHERE owner = %s AND repo = %s
                  AND (state = 'pending' OR (state = 'watch' AND checked_at <= %s))
                ORDER BY checked_at ASC, run_number ASC
                LIMIT %s
                """
            ).format(_qualified("pipeline_reconcile_state")),
            (owner, repo, watch_before, max(1, int(limit))),
        ).fetchall()
    return [
        decoded
        for row in rows
        if (decoded := _decode_production_state(row)) is not None
    ]


def remember_production_candidate(
    owner: str,
    repo: str,
    item: dict,
) -> None:
    run_number = int(item.get("index_in_repo") or 0)
    run_id = int(item.get("id") or 0)
    if not run_number or not run_id:
        return
    fingerprint = _production_run_fingerprint(item)
    current = latest_production_reconcile_state(owner, repo, run_number)
    if current and current.get("fingerprint") == fingerprint:
        return
    record_production_reconcile_state(
        owner,
        repo,
        run_number=run_number,
        state="pending",
        run_id=run_id,
        fingerprint=fingerprint,
        updated=str(item.get("updated") or item.get("updated_at") or ""),
        revision=(
            recorded_production_revision(owner, repo, run_number) or None
        ),
    )


def list_tracked_repositories() -> list[tuple[str, str]]:
    """Return repositories that have used the NyankoFace pipeline control plane."""
    initialize()
    with _transaction() as db:
        rows = db.execute(
            sql.SQL(
                """
                SELECT owner, repo
                FROM {}
                WHERE action NOT LIKE %s ESCAPE %s
                GROUP BY owner, repo
                ORDER BY MAX(id) DESC
                """
            ).format(_qualified("pipeline_audit")),
            ("\\_reconcile\\_%", "\\"),
        ).fetchall()
    return [(str(row["owner"]), str(row["repo"])) for row in rows]


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"token {token}",
    }


def _api_path(owner: str, repo: str, suffix: str) -> str:
    return (
        f"{config.FORGEJO_API}/repos/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/{suffix.lstrip('/')}"
    )


async def list_workflows(owner: str, repo: str, token: str) -> list[dict]:
    repo_info = await forgejo.get_repo_info(owner, repo, token)
    branch = repo_info.get("default_branch") or "main"
    async with httpx.AsyncClient(timeout=20.0) as client:
        for directory in (".forgejo/workflows", ".github/workflows"):
            response = await client.get(
                _api_path(owner, repo, f"contents/{directory}"),
                headers=_headers(token),
                params={"ref": branch},
            )
            if response.status_code == 404:
                continue
            if response.status_code != 200:
                raise PipelineError(
                    f"Forgejo returned HTTP {response.status_code} while listing workflows."
                )
            entries = response.json()
            workflows = [
                {
                    "name": entry.get("name"),
                    "path": entry.get("path"),
                    "sha": entry.get("sha"),
                    "source": directory,
                }
                for entry in entries
                if str(entry.get("name", "")).endswith((".yml", ".yaml"))
            ]
            if workflows:
                return workflows
    return []


async def list_runner_targets(owner: str, repo: str, token: str) -> list[dict]:
    runners: dict[str, dict] = {}
    endpoints = (
        f"orgs/{quote(owner, safe='')}/actions/runners",
        f"repos/{quote(owner, safe='')}/{quote(repo, safe='')}/actions/runners",
    )
    observed = False
    async with httpx.AsyncClient(timeout=20.0) as client:
        for endpoint in endpoints:
            try:
                response = await client.get(
                    f"{config.FORGEJO_API}/{endpoint}", headers=_headers(token),
                )
            except httpx.HTTPError as exc:
                raise PipelineError("Runner lookup failed.", retry_safe=True) from exc
            if response.status_code in (403, 404):
                continue
            if response.status_code != 200:
                raise PipelineError("Runner lookup failed.", retry_safe=True)
            observed = True
            try:
                payload = response.json()
            except (ValueError, AttributeError) as exc:
                raise PipelineError("Runner lookup was invalid.", retry_safe=True) from exc
            if not isinstance(payload, list):
                raise PipelineError("Runner lookup was invalid.", retry_safe=True)
            for item in payload:
                if not isinstance(item, dict):
                    raise PipelineError("Runner lookup was invalid.", retry_safe=True)
                labels = item.get("labels", [])
                if not isinstance(labels, list) or not all(
                    isinstance(label, str) for label in labels
                ):
                    raise PipelineError("Runner lookup was invalid.", retry_safe=True)
                identity = str(item.get("uuid") or item.get("id") or "")
                if identity:
                    runners[identity] = {**item, "labels": labels}

    targets = (
        ("node20", "CPU · Node.js 20"),
        ("gpu", "GPU · CUDA"),
    )
    result: list[dict] = []
    for value, label in targets:
        matching = [
            item
            for item in runners.values()
            if value in (item.get("labels") or [])
        ]
        online = [
            item
            for item in matching
            if str(item.get("status") or "").lower() != "offline"
        ]
        if online:
            status = "online"
            available: bool | None = True
        elif matching:
            status = "offline"
            available = False
        elif observed:
            status = "unregistered"
            available = False
        else:
            status = "unknown"
            available = None
        result.append(
            {
                "value": value,
                "label": label,
                "available": available,
                "status": status,
                "online": len(online),
                "registered": len(matching),
            }
        )
    return result


def _run_environment(run: dict, default_branch: str) -> str:
    try:
        payload = json.loads(str(run.get("event_payload") or "{}"))
    except json.JSONDecodeError:
        payload = {}
    if str(run.get("event") or "").lower() == "release":
        return "production"
    refs = (
        run.get("ref"),
        payload.get("ref"),
        payload.get("git_ref"),
    )
    if str(payload.get("ref_type") or "").lower() == "tag" or any(
        str(ref or "").startswith("refs/tags/") for ref in refs
    ):
        return "production"
    requested = str((payload.get("inputs") or {}).get("environment") or "")
    if requested in PIPELINE_ENVIRONMENTS:
        return requested
    title = str(run.get("display_title") or run.get("name") or "").lower()
    for environment in PIPELINE_ENVIRONMENTS:
        if f"nyankoface {environment} " in title or f"nyankoface {environment}·" in title:
            return environment
    if run.get("event") in ("pull_request", "pull_request_target"):
        return "preview"
    branch = str(run.get("head_branch") or "")
    return "production" if branch == default_branch else "staging"


def _run_environment_from_jobs(
    jobs: list[dict],
    run: dict,
    default_branch: str,
) -> str:
    try:
        payload = json.loads(str(run.get("event_payload") or "{}"))
    except (TypeError, ValueError):
        payload = {}
    refs = (
        run.get("ref"),
        payload.get("ref"),
        payload.get("git_ref"),
    )
    if (
        str(run.get("event") or "").lower() == "release"
        or str(payload.get("ref_type") or "").lower() == "tag"
        or any(str(ref or "").startswith("refs/tags/") for ref in refs)
    ):
        return "production"
    active = [
        (
            str(job.get("name") or "").lower(),
            str(job.get("conclusion") or job.get("status") or "").lower(),
        )
        for job in jobs
    ]
    for environment, labels in (
        ("preview", ("preview artifact",)),
        ("staging", ("staging artifact",)),
        ("production", ("publish production pages", "restart production space")),
    ):
        if any(
            any(label in name for label in labels)
            and status not in {"", "skipped", "cancelled", "blocked"}
            for name, status in active
        ):
            return environment
    requested = str((payload.get("inputs") or {}).get("environment") or "")
    if requested in PIPELINE_ENVIRONMENTS:
        return requested
    if run.get("event") in ("pull_request", "pull_request_target"):
        return "preview"
    # A default-branch workflow is not proof that anything reached production.
    # Unrecognized and test-only workflows remain staging until a deployment
    # job or explicit workflow_dispatch input proves otherwise.
    return "staging"


def _deployed_revision(run: dict) -> str:
    recorded = str(run.get("deployed_revision") or "").strip()
    if recorded:
        return recorded
    try:
        payload = json.loads(str(run.get("event_payload") or "{}"))
    except (TypeError, ValueError):
        payload = {}
    revision = str((payload.get("inputs") or {}).get("revision") or "").strip()
    return revision or str(run.get("head_sha") or "").strip()


def _effective_run_status(api_status: str, jobs: list[dict]) -> str:
    """Prefer the actual job state over a dependent job's aggregate state."""
    statuses = {
        str(job.get("conclusion") or job.get("status") or "").lower()
        for job in jobs
    }
    statuses.discard("")
    if statuses & {"running", "in_progress"}:
        return "running"
    if statuses & {"waiting", "queued", "pending"}:
        return "waiting"
    if statuses & {"failure", "failed", "timed_out"}:
        return "failure"
    if "cancelled" in statuses:
        return "cancelled"
    if "success" in statuses and statuses <= {"success", "blocked", "skipped"}:
        return "success"
    return api_status


def _pull_request_approval_url(owner: str, repo: str, item: dict) -> str | None:
    if not item.get("need_approval"):
        return None
    try:
        payload = json.loads(str(item.get("event_payload") or "{}"))
    except (TypeError, ValueError):
        return None
    pull_request = payload.get("pull_request") or {}
    number = pull_request.get("number") or payload.get("number")
    try:
        pull_number = int(number)
    except (TypeError, ValueError):
        return None
    if pull_number <= 0:
        return None
    return (
        f"/git/{quote(owner, safe='')}/{quote(repo, safe='')}/pulls/"
        f"{pull_number}#pull-request-trust-panel"
    )


def _deployment_key(item: dict, run_number: int, environment: str) -> tuple[str, bool]:
    if environment == "staging":
        return "current", False
    try:
        payload = json.loads(str(item.get("event_payload") or "{}"))
    except (TypeError, ValueError):
        payload = {}
    if item.get("event") in ("pull_request", "pull_request_target"):
        pull_request = payload.get("pull_request") or {}
        number = pull_request.get("number") or payload.get("number")
        try:
            pull_number = int(number)
        except (TypeError, ValueError):
            pull_number = 0
        if pull_number > 0:
            return f"pr-{pull_number}", str(payload.get("action") or "") == "closed"
    return f"run-{run_number}", False


def _deployment_url(owner: str, repo: str, environment: str, key: str) -> str:
    base = config.PUBLIC_BASE_URL.rstrip("/")
    if environment == "preview":
        return (
            f"{base}/previews/{quote(owner, safe='')}/"
            f"{quote(repo, safe='')}/{quote(key, safe='')}/"
        )
    return f"{base}/staging/{quote(owner, safe='')}/{quote(repo, safe='')}/"


def _deployment_job_succeeded(jobs: list[dict], environment: str) -> bool:
    expected = (
        "publish preview site"
        if environment == "preview"
        else "publish staging site"
    )
    return any(
        expected in str(job.get("name") or "").lower()
        and str(job.get("conclusion") or job.get("status") or "").lower()
        == "success"
        for job in jobs
    )


async def _read_response_limited(
    response: httpx.Response,
    *,
    limit: int,
) -> bytes:
    declared = response.headers.get("content-length")
    if declared:
        try:
            if int(declared) > limit:
                raise preview_artifacts.PreviewArtifactError(
                    "Artifact ZIP exceeds the configured size limit."
                )
        except ValueError:
            pass
    content = bytearray()
    async for chunk in response.aiter_bytes():
        if len(content) + len(chunk) > limit:
            raise preview_artifacts.PreviewArtifactError(
                "Artifact ZIP exceeds the configured size limit."
            )
        content.extend(chunk)
    return bytes(content)


async def _reconcile_environment_site(
    owner: str,
    repo: str,
    item: dict,
    jobs: list[dict],
    *,
    environment: str,
    run_number: int,
    token: str,
    public_repo: bool,
) -> dict | None:
    if environment not in {"preview", "staging"} or not public_repo:
        return None
    key, closed = _deployment_key(item, run_number, environment)
    if closed:
        transition = await asyncio.to_thread(
            preview_artifacts.mark_preview_closed,
            owner,
            repo,
            key,
            run_number=run_number,
        )
        if transition.get("advanced"):
            await asyncio.to_thread(
                record_event,
                owner,
                repo,
                "expire_preview",
                "nyankoface-deployer",
                run_number=run_number,
                environment=environment,
            )
        return None
    if not _deployment_job_succeeded(jobs, environment):
        return None

    forgejo_run_id = int(item.get("id") or 0)
    async with httpx.AsyncClient(timeout=30.0) as client:
        artifacts_response = await client.get(
            _api_path(
                owner,
                repo,
                f"actions/runs/{forgejo_run_id}/artifacts",
            ),
            headers=_headers(token),
        )
        if artifacts_response.status_code != 200:
            return None
        payload = artifacts_response.json()
        artifacts = payload if isinstance(payload, list) else payload.get("artifacts") or []
        prefix = f"nyankoface-{environment}-site-"
        matching = [
            artifact
            for artifact in artifacts
            if str(artifact.get("name") or "").startswith(prefix)
            and not bool(artifact.get("expired"))
        ]
        if not matching:
            return None
        artifact = max(matching, key=lambda value: int(value.get("id") or 0))
        artifact_id = int(artifact.get("id") or 0)
        try:
            async with client.stream(
                "GET",
                _api_path(owner, repo, f"actions/artifacts/{artifact_id}/zip"),
                headers=_headers(token),
            ) as download:
                if download.status_code != 200:
                    return None
                artifact_zip = await _read_response_limited(
                    download,
                    limit=preview_artifacts.MAX_ARCHIVE_BYTES,
                )
        except (httpx.HTTPError, preview_artifacts.PreviewArtifactError):
            return None
    try:
        if environment in {"preview", "staging"}:
            deleted_sha = await asyncio.to_thread(
                preview_artifacts.deletion_source_sha,
                artifact_zip,
                expected_repository=f"{owner}/{repo}",
                expected_run_id=forgejo_run_id,
                expected_run_number=run_number,
                expected_environment=environment,
            )
            if deleted_sha is not None:
                if environment == "preview":
                    await asyncio.to_thread(
                        preview_artifacts.mark_preview_deleted,
                        owner,
                        repo,
                        key,
                        run_number=run_number,
                        source_sha=deleted_sha,
                    )
                else:
                    await asyncio.to_thread(
                        preview_artifacts.mark_staging_deleted,
                        owner,
                        repo,
                        run_number=run_number,
                        source_sha=deleted_sha,
                    )
                await asyncio.to_thread(
                    record_event,
                    owner,
                    repo,
                    f"expire_{environment}",
                    "nyankoface-deployer",
                    run_number=run_number,
                    environment=environment,
                    revision=deleted_sha,
                )
                return None
        source_sha = await asyncio.to_thread(
            preview_artifacts.source_sha,
            artifact_zip,
            expected_repository=f"{owner}/{repo}",
            expected_run_id=forgejo_run_id,
            expected_run_number=run_number,
        )
        existing = await asyncio.to_thread(
            preview_artifacts.metadata,
            owner,
            repo,
            environment,
            key,
        )
        if (
            existing
            and int(existing.get("run_id") or 0) == forgejo_run_id
            and str(existing.get("source_sha") or "") == source_sha
        ):
            return {
                **existing,
                "url": _deployment_url(owner, repo, environment, key),
            }
        deployed = await asyncio.to_thread(
            preview_artifacts.publish,
            owner=owner,
            repo=repo,
            environment=environment,
            key=key,
            artifact_zip=artifact_zip,
            expected_repository=f"{owner}/{repo}",
            expected_sha=source_sha,
            expected_run_id=forgejo_run_id,
            expected_run_number=run_number,
            artifact_id=artifact_id,
        )
    except preview_artifacts.PreviewArtifactError:
        return None
    await asyncio.to_thread(
        record_event,
        owner,
        repo,
        f"publish_{environment}",
        "nyankoface-deployer",
        run_number=run_number,
        environment=environment,
        revision=source_sha,
    )
    return {
        **deployed,
        "url": _deployment_url(owner, repo, environment, key),
    }


async def _reconcile_production_revision(
    owner: str,
    repo: str,
    item: dict,
    jobs: list[dict],
    *,
    run_number: int,
    token: str,
    detailed: bool = False,
) -> str | tuple[str, dict]:
    updated = str(item.get("updated") or item.get("updated_at") or "")
    fingerprint = _production_run_fingerprint(item)
    attempt = max(
        (
            int(job.get("attempt") or 0)
            for job in jobs
            if "publish production pages"
            in str(job.get("name") or "").lower()
        ),
        default=0,
    )

    def result(
        revision: str,
        state: str,
        *,
        artifact_id: int = 0,
        expires_at: str = "",
    ) -> str | tuple[str, dict]:
        if not detailed:
            return revision
        return revision, {
            "state": state,
            "run_id": int(item.get("id") or 0),
            "fingerprint": fingerprint,
            "updated": updated,
            "attempt": attempt,
            "artifact_id": artifact_id,
            "expires_at": expires_at,
        }

    recorded = await asyncio.to_thread(
        recorded_production_revision,
        owner,
        repo,
        run_number,
    )
    if not any(
        "publish production pages" in str(job.get("name") or "").lower()
        and str(job.get("conclusion") or job.get("status") or "").lower()
        == "success"
        for job in jobs
    ):
        run_status = str(
            item.get("conclusion") or item.get("status") or ""
        ).lower()
        terminal = run_status in {
            "failure",
            "cancelled",
            "canceled",
            "skipped",
        }
        return result(
            recorded,
            "terminal" if terminal else "pending",
        )

    forgejo_run_id = int(item.get("id") or 0)
    if not forgejo_run_id:
        return result(recorded, "pending")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            _api_path(
                owner,
                repo,
                f"actions/runs/{forgejo_run_id}/artifacts",
            ),
            headers=_headers(token),
        )
    if response.status_code != 200:
        return result(recorded, "pending")
    payload = response.json()
    artifacts = (
        payload if isinstance(payload, list) else payload.get("artifacts") or []
    )
    prefix = "nyankoface-production-revision-"
    revision_artifacts = [
        artifact
        for artifact in artifacts
        if str(artifact.get("name") or "").startswith(prefix)
        and not bool(artifact.get("expired"))
        and re.fullmatch(
            r"[0-9a-fA-F]{40,64}",
            str(artifact.get("name") or "")[len(prefix) :],
        )
    ]
    latest = max(
        revision_artifacts,
        key=lambda artifact: (
            int(artifact.get("id") or 0),
            str(artifact.get("created_at") or ""),
        ),
        default=None,
    )
    if latest is None:
        matching_expired = any(
            str(artifact.get("name") or "").startswith(prefix)
            and bool(artifact.get("expired"))
            for artifact in artifacts
        )
        return result(
            recorded,
            "terminal" if matching_expired else "pending",
        )
    revision = str(latest.get("name") or "")[len(prefix) :].lower()
    if revision == recorded:
        return result(
            recorded,
            "watch",
            artifact_id=int(latest.get("id") or 0),
            expires_at=str(latest.get("expires_at") or ""),
        )
    await asyncio.to_thread(
        record_event,
        owner,
        repo,
        "deploy_production",
        "nyankoface-deployer",
        run_number=run_number,
        environment="production",
        revision=revision,
    )
    return result(
        revision,
        "watch",
        artifact_id=int(latest.get("id") or 0),
        expires_at=str(latest.get("expires_at") or ""),
    )


async def reconcile_repository_deployments(
    owner: str,
    repo: str,
    token: str,
) -> list[dict]:
    """Reconcile deployments with a bounded Forgejo request budget.

    The newest page keeps active preview/staging runs fresh. A persistent
    run-number cursor discovers older gaps in fixed batches after downtime,
    while unresolved production attempts remain in an internal watermark
    queue until their job/artifact metadata becomes visible.
    """
    repo_info = await forgejo.get_repo_info(owner, repo, token)
    public_repo = not bool(repo_info.get("private"))
    default_branch = repo_info.get("default_branch") or "main"
    cursor = await asyncio.to_thread(
        production_reconcile_cursor,
        owner,
        repo,
    )
    api_runs: list[dict] = []
    seen_run_ids: set[int] = set()
    discovered_cursor = cursor
    async with httpx.AsyncClient(timeout=20.0) as client:
        head_response = await client.get(
            _api_path(owner, repo, "actions/runs"),
            headers=_headers(token),
            params={"limit": 50, "page": 1},
        )
        if head_response.status_code != 200:
            raise PipelineError(
                f"Forgejo returned HTTP {head_response.status_code} while reconciling pipeline runs."
            )
        head_payload = head_response.json()
        head_runs = head_payload.get("workflow_runs") or []
        head_run_ids = {
            int(item.get("id") or 0)
            for item in head_runs
            if int(item.get("id") or 0)
        }
        by_run_number: dict[int, dict] = {}
        for item in head_runs:
            run_id = int(item.get("id") or 0)
            run_number = int(item.get("index_in_repo") or 0)
            if run_id and run_id not in seen_run_ids:
                seen_run_ids.add(run_id)
                api_runs.append(item)
            if run_number:
                by_run_number[run_number] = item
        newest_run_number = max(by_run_number, default=cursor)
        if cursor == 0:
            # Process the newest bounded page now, then retain a negative
            # run-number watermark so older history is backfilled in later
            # bounded cycles instead of being skipped or scanned at once.
            discovery_items = api_runs
            oldest_run_number = min(by_run_number, default=1)
            discovered_cursor = (
                -(oldest_run_number - 1)
                if oldest_run_number > 1
                else newest_run_number
            )
        elif cursor < 0:
            backfill_end = -cursor
            backfill_start = max(
                1,
                backfill_end - config.PIPELINE_DISCOVERY_BATCH_SIZE + 1,
            )
            discovery_items = []
            for run_number in range(backfill_start, backfill_end + 1):
                exact_response = await client.get(
                    _api_path(owner, repo, "actions/runs"),
                    headers=_headers(token),
                    params={"limit": 2, "run_number": run_number},
                )
                if exact_response.status_code != 200:
                    raise PipelineError(
                        "Forgejo returned HTTP "
                        f"{exact_response.status_code} while backfilling "
                        f"pipeline run {run_number}."
                    )
                exact_runs = (
                    exact_response.json().get("workflow_runs") or []
                )
                item = next(
                    (
                        candidate
                        for candidate in exact_runs
                        if int(candidate.get("index_in_repo") or 0)
                        == run_number
                    ),
                    None,
                )
                if item is not None:
                    discovery_items.append(item)
                    run_id = int(item.get("id") or 0)
                    if run_id and run_id not in seen_run_ids:
                        seen_run_ids.add(run_id)
                        api_runs.append(item)
            discovered_cursor = (
                -(backfill_start - 1)
                if backfill_start > 1
                else newest_run_number
            )
        else:
            discovery_end = min(
                newest_run_number,
                cursor + config.PIPELINE_DISCOVERY_BATCH_SIZE,
            )
            discovery_items = []
            for run_number in range(cursor + 1, discovery_end + 1):
                item = by_run_number.get(run_number)
                if item is None:
                    exact_response = await client.get(
                        _api_path(owner, repo, "actions/runs"),
                        headers=_headers(token),
                        params={"limit": 2, "run_number": run_number},
                    )
                    if exact_response.status_code != 200:
                        raise PipelineError(
                            "Forgejo returned HTTP "
                            f"{exact_response.status_code} while discovering "
                            f"pipeline run {run_number}."
                        )
                    exact_payload = exact_response.json()
                    exact_runs = exact_payload.get("workflow_runs") or []
                    item = next(
                        (
                            candidate
                            for candidate in exact_runs
                            if int(candidate.get("index_in_repo") or 0)
                            == run_number
                        ),
                        None,
                    )
                if item is not None:
                    discovery_items.append(item)
                    run_id = int(item.get("id") or 0)
                    if run_id and run_id not in seen_run_ids:
                        seen_run_ids.add(run_id)
                        api_runs.append(item)
                discovered_cursor = run_number

        observed_production_ids: set[int] = set()
        for item in [*head_runs, *discovery_items]:
            run_id = int(item.get("id") or 0)
            if run_id in observed_production_ids:
                continue
            observed_production_ids.add(run_id)
            environment = _run_environment(
                {
                    "event": item.get("event"),
                    "event_payload": item.get("event_payload"),
                    "ref": item.get("ref"),
                    "head_branch": item.get("prettyref"),
                    "display_title": item.get("title"),
                },
                default_branch,
            )
            if environment == "production":
                await asyncio.to_thread(
                    remember_production_candidate,
                    owner,
                    repo,
                    item,
                )

        candidate_groups: dict[
            tuple[str, str],
            list[tuple[int, dict]],
        ] = {}
        for item in api_runs:
            run_number = int(item.get("index_in_repo") or 0)
            if not run_number:
                continue
            environment = _run_environment(
                {
                    "event": item.get("event"),
                    "event_payload": item.get("event_payload"),
                    "ref": item.get("ref"),
                    "head_branch": item.get("prettyref"),
                    "display_title": item.get("title"),
                },
                default_branch,
            )
            if environment not in {"preview", "staging", "production"}:
                continue
            if (
                cursor < 0
                and environment == "staging"
                and int(item.get("id") or 0) not in head_run_ids
            ):
                # Historical staging artifacts must never replace the newest
                # staging site while a bounded bootstrap walks backwards.
                continue
            if not public_repo and environment != "production":
                continue
            if environment == "production":
                continue
            key, _closed = _deployment_key(item, run_number, environment)
            group = (environment, key)
            candidate_groups.setdefault(group, []).append((run_number, item))

        reconciled: list[dict] = []
        production_states = await asyncio.to_thread(
            due_production_reconcile_states,
            owner,
            repo,
            config.PRODUCTION_RECONCILE_BATCH_SIZE,
        )
        for state in production_states:
            run_number = int(state.get("run_number") or 0)
            item = by_run_number.get(run_number)
            if item is None:
                run_response = await client.get(
                    _api_path(owner, repo, "actions/runs"),
                    headers=_headers(token),
                    params={"limit": 2, "run_number": run_number},
                )
                if run_response.status_code == 200:
                    run_payload = run_response.json()
                    item = next(
                        (
                            candidate
                            for candidate in (
                                run_payload.get("workflow_runs") or []
                            )
                            if int(
                                candidate.get("index_in_repo") or 0
                            )
                            == run_number
                        ),
                        None,
                    )
            if item is None:
                await asyncio.to_thread(
                    record_production_reconcile_state,
                    owner,
                    repo,
                    run_number=run_number,
                    state="pending",
                    run_id=int(state.get("run_id") or 0),
                    fingerprint=str(state.get("fingerprint") or ""),
                    updated=str(state.get("updated") or ""),
                    attempt=int(state.get("attempt") or 0),
                    artifact_id=int(state.get("artifact_id") or 0),
                    expires_at=str(state.get("expires_at") or ""),
                    revision=str(state.get("revision") or "") or None,
                    force=True,
                )
                continue

            current_fingerprint = _production_run_fingerprint(item)
            if (
                state.get("state") == "watch"
                and state.get("fingerprint") == current_fingerprint
            ):
                expires_at = str(state.get("expires_at") or "")
                expired = False
                if expires_at:
                    try:
                        expired = (
                            datetime.fromisoformat(
                                expires_at.replace("Z", "+00:00")
                            )
                            <= datetime.now(timezone.utc)
                        )
                    except (TypeError, ValueError):
                        expired = False
                await asyncio.to_thread(
                    record_production_reconcile_state,
                    owner,
                    repo,
                    run_number=run_number,
                    state="terminal" if expired else "watch",
                    run_id=int(item.get("id") or 0),
                    fingerprint=current_fingerprint,
                    updated=str(
                        item.get("updated")
                        or item.get("updated_at")
                        or ""
                    ),
                    attempt=int(state.get("attempt") or 0),
                    artifact_id=int(state.get("artifact_id") or 0),
                    expires_at=expires_at,
                    revision=str(state.get("revision") or "") or None,
                    force=not expired,
                )
                continue

            run_id = int(item.get("id") or 0)
            jobs_response = await client.get(
                _api_path(owner, repo, f"actions/runs/{run_id}/jobs"),
                headers=_headers(token),
            )
            if jobs_response.status_code != 200:
                await asyncio.to_thread(
                    record_production_reconcile_state,
                    owner,
                    repo,
                    run_number=run_number,
                    state="pending",
                    run_id=run_id,
                    fingerprint=current_fingerprint,
                    updated=str(
                        item.get("updated")
                        or item.get("updated_at")
                        or ""
                    ),
                    revision=str(state.get("revision") or "") or None,
                    force=True,
                )
                continue
            jobs_payload = jobs_response.json()
            jobs = (
                jobs_payload
                if isinstance(jobs_payload, list)
                else jobs_payload.get("jobs") or []
            )
            outcome_value = await _reconcile_production_revision(
                owner,
                repo,
                item,
                jobs,
                run_number=run_number,
                token=token,
                detailed=True,
            )
            if isinstance(outcome_value, tuple):
                revision, outcome = outcome_value
            else:
                revision = str(outcome_value or "")
                outcome = {
                    "state": "watch" if revision else "pending",
                    "run_id": run_id,
                    "fingerprint": current_fingerprint,
                    "updated": str(
                        item.get("updated")
                        or item.get("updated_at")
                        or ""
                    ),
                    "attempt": 0,
                    "artifact_id": 0,
                    "expires_at": "",
                }
            await asyncio.to_thread(
                record_production_reconcile_state,
                owner,
                repo,
                run_number=run_number,
                state=str(outcome["state"]),
                run_id=int(outcome["run_id"]),
                fingerprint=str(outcome["fingerprint"]),
                updated=str(outcome.get("updated") or ""),
                attempt=int(outcome.get("attempt") or 0),
                artifact_id=int(outcome.get("artifact_id") or 0),
                expires_at=str(outcome.get("expires_at") or ""),
                revision=revision or None,
                force=True,
            )
            if revision:
                reconciled.append(
                    {
                        "environment": "production",
                        "run_number": run_number,
                        "source_sha": revision,
                    }
                )

        latest_manual_preview: tuple[int, str] | None = None
        removed_preview_keys: set[str] = set()

        async def prune_manual_previews(
            protected_keys: tuple[str, ...] = (),
        ) -> None:
            if not public_repo:
                return
            removed = await asyncio.to_thread(
                preview_artifacts.prune_run_previews,
                owner,
                repo,
                protected_keys=protected_keys,
            )
            for removed_key in removed:
                if removed_key in removed_preview_keys:
                    continue
                removed_preview_keys.add(removed_key)
                await asyncio.to_thread(
                    record_event,
                    owner,
                    repo,
                    "expire_manual_preview",
                    "nyankoface-deployer",
                    environment="preview",
                    workflow=removed_key,
                )

        # Bound the existing on-disk set before any retained backlog artifact
        # can be expanded. PR previews and malformed directories are excluded
        # by prune_run_previews and remain untouched.
        await prune_manual_previews()

        grouped_candidates = list(candidate_groups.items())
        manual_preview_groups = sorted(
            (
                entry
                for entry in grouped_candidates
                if entry[0][0] == "preview"
                and re.fullmatch(r"run-[1-9][0-9]*", entry[0][1])
            ),
            key=lambda entry: int(entry[0][1].removeprefix("run-")),
            reverse=True,
        )
        ordered_groups = (
            [
                entry
                for entry in grouped_candidates
                if entry not in manual_preview_groups
            ]
            + manual_preview_groups
        )
        retained_manual_previews = 0
        manual_preview_limit = config.PREVIEW_RUN_MAX_COUNT

        for (environment, _key), candidates in ordered_groups:
            manual_preview = (
                environment == "preview"
                and re.fullmatch(r"run-[1-9][0-9]*", _key) is not None
            )
            if (
                manual_preview
                and retained_manual_previews >= manual_preview_limit
            ):
                continue
            candidates.sort(key=lambda value: value[0], reverse=True)
            selected: tuple[int, dict, list[dict]] | None = None
            if environment == "preview":
                # A close event is a tombstone for this PR and must supersede
                # every older successful preview.
                run_number, item = candidates[0]
                _deployment_key_value, closed = _deployment_key(
                    item,
                    run_number,
                    environment,
                )
                jobs = []
                if not closed:
                    run_id = int(item.get("id") or 0)
                    jobs_response = await client.get(
                        _api_path(
                            owner,
                            repo,
                            f"actions/runs/{run_id}/jobs",
                        ),
                        headers=_headers(token),
                    )
                    if jobs_response.status_code != 200:
                        continue
                    jobs_payload = jobs_response.json()
                    jobs = (
                        jobs_payload
                        if isinstance(jobs_payload, list)
                        else jobs_payload.get("jobs") or []
                    )
                selected = (run_number, item, jobs)
            else:
                # A failed or still-running staging execution must not hide
                # the newest previously successful staging artifact.
                for run_number, item in candidates:
                    run_id = int(item.get("id") or 0)
                    jobs_response = await client.get(
                        _api_path(
                            owner,
                            repo,
                            f"actions/runs/{run_id}/jobs",
                        ),
                        headers=_headers(token),
                    )
                    if jobs_response.status_code != 200:
                        continue
                    jobs_payload = jobs_response.json()
                    jobs = (
                        jobs_payload
                        if isinstance(jobs_payload, list)
                        else jobs_payload.get("jobs") or []
                    )
                    if _deployment_job_succeeded(jobs, "staging"):
                        selected = (run_number, item, jobs)
                        break
            if selected is None:
                continue
            run_number, item, jobs = selected
            deployment = await _reconcile_environment_site(
                owner,
                repo,
                item,
                jobs,
                environment=environment,
                run_number=run_number,
                token=token,
                public_repo=public_repo,
            )
            if deployment:
                reconciled.append(deployment)
                deployment_key = str(deployment.get("key") or "")
                if manual_preview:
                    retained_manual_previews += 1
                    if (
                        latest_manual_preview is None
                        or run_number > latest_manual_preview[0]
                    ):
                        latest_manual_preview = (run_number, deployment_key)
        await prune_manual_previews(
            (
                (latest_manual_preview[1],)
                if latest_manual_preview is not None
                else ()
            )
        )
        if removed_preview_keys:
            reconciled = [
                deployment
                for deployment in reconciled
                if str(deployment.get("key") or "") not in removed_preview_keys
            ]
        if discovered_cursor != cursor and (
            cursor == 0 or discovered_cursor > cursor
        ):
            await asyncio.to_thread(
                record_production_reconcile_cursor,
                owner,
                repo,
                discovered_cursor,
            )
    return reconciled


async def reconcile_tracked_repositories(token: str) -> None:
    repositories = await asyncio.to_thread(list_tracked_repositories)
    for owner, repo in repositories:
        try:
            await reconcile_repository_deployments(owner, repo, token)
        except Exception as exc:  # noqa: BLE001 - one repository must not stop the worker
            logger.warning(
                "pipeline reconciliation failed for %s/%s: %s",
                owner,
                repo,
                exc,
            )


async def reconcile_loop() -> None:
    """Continuously reconcile managed repositories independently of the UI."""
    while True:
        try:
            token = config.read_forgejo_token()
            if token:
                await reconcile_tracked_repositories(token)
        except Exception as exc:  # noqa: BLE001 - keep the service loop alive
            logger.warning("pipeline reconciliation cycle failed: %s", exc)
        await asyncio.sleep(config.PIPELINE_RECONCILE_INTERVAL_SECONDS)


async def list_runs(
    owner: str,
    repo: str,
    token: str,
    *,
    limit: int = 30,
    page: int = 1,
    include_pagination: bool = False,
    reconcile_deployments: bool = True,
) -> list[dict] | dict:
    repo_info = await forgejo.get_repo_info(owner, repo, token)
    default_branch = repo_info.get("default_branch") or "main"
    effective_page = max(1, page)
    effective_limit = max(1, min(limit, 50))
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            _api_path(owner, repo, "actions/runs"),
            headers=_headers(token),
            params={"page": effective_page, "limit": effective_limit},
        )
    if response.status_code != 200:
        raise PipelineError(
            f"Forgejo returned HTTP {response.status_code} while listing pipeline runs."
        )
    response_payload = response.json()
    api_runs = response_payload.get("workflow_runs") or []
    total_count = int(response_payload.get("total_count") or len(api_runs))

    async def fetch_jobs(item: dict) -> list[dict]:
        run_id = int(item.get("id") or 0)
        if not run_id:
            return []
        async with httpx.AsyncClient(timeout=20.0) as client:
            jobs_response = await client.get(
                _api_path(owner, repo, f"actions/runs/{run_id}/jobs"),
                headers=_headers(token),
            )
        if jobs_response.status_code != 200:
            return []
        payload = jobs_response.json()
        return payload if isinstance(payload, list) else payload.get("jobs") or []

    job_groups = await asyncio.gather(*(fetch_jobs(item) for item in api_runs))
    public_repo = not bool(repo_info.get("private"))
    reconcile_candidates: dict[tuple[str, str], int] = {}
    if public_repo and reconcile_deployments:
        for item, run_jobs in zip(api_runs, job_groups, strict=True):
            run_number = int(item.get("index_in_repo") or 0)
            if not run_number:
                continue
            environment = _run_environment_from_jobs(
                run_jobs,
                {
                    "event": item.get("event"),
                    "event_payload": item.get("event_payload"),
                    "head_branch": item.get("prettyref"),
                    "display_title": item.get("title"),
                },
                default_branch,
            )
            if environment not in {"preview", "staging"}:
                continue
            key, _closed = _deployment_key(item, run_number, environment)
            if (
                environment == "staging"
                and not _deployment_job_succeeded(run_jobs, environment)
            ):
                continue
            group = (environment, key)
            reconcile_candidates[group] = max(
                run_number,
                reconcile_candidates.get(group, 0),
            )

    result = []
    for item, run_jobs in zip(api_runs, job_groups, strict=True):
        run_number = int(item.get("index_in_repo") or 0)
        if not run_number:
            continue
        actor = item.get("trigger_user") or {}
        status = _effective_run_status(
            str(item.get("status") or "waiting").lower(),
            run_jobs,
        )
        environment = _run_environment_from_jobs(
            run_jobs,
            {
                "event": item.get("event"),
                "event_payload": item.get("event_payload"),
                "head_branch": item.get("prettyref"),
                "display_title": item.get("title"),
            },
            default_branch,
        )
        deployment = None
        if reconcile_deployments and environment in {"preview", "staging"}:
            deployment_key, _closed = _deployment_key(
                item,
                run_number,
                environment,
            )
            if reconcile_candidates.get((environment, deployment_key)) == run_number:
                deployment = await _reconcile_environment_site(
                    owner,
                    repo,
                    item,
                    run_jobs,
                    environment=environment,
                    run_number=run_number,
                    token=token,
                    public_repo=public_repo,
                )
        production_revision = ""
        if (
            reconcile_deployments
            and environment == "production"
            and status == "success"
        ):
            production_revision = await _reconcile_production_revision(
                owner,
                repo,
                item,
                run_jobs,
                run_number=run_number,
                token=token,
            )
        result.append(
            {
                "id": run_number,
                "forgejo_run_id": int(item.get("id") or 0),
                "name": str(item.get("workflow_id") or "Pipeline"),
                "head_branch": str(item.get("prettyref") or ""),
                "head_sha": str(item.get("commit_sha") or ""),
                "event": str(
                    item.get("event")
                    or ("workflow_dispatch" if item.get("event_payload") else "")
                ),
                "deployed_revision": production_revision
                or _deployed_revision(
                    {
                        "event_payload": item.get("event_payload"),
                        "head_sha": item.get("commit_sha"),
                    }
                ),
                "display_title": str(
                    item.get("title") or item.get("workflow_id") or "Pipeline"
                ),
                "status": status,
                "run_started_at": item.get("started"),
                "updated_at": (
                    item.get("updated_at")
                    or item.get("updated")
                    or item.get("stopped")
                    or item.get("started")
                ),
                "environment": environment,
                "environment_url": deployment.get("url") if deployment else None,
                "deployment": deployment,
                "run_number": run_number,
                "job_count": len(run_jobs),
                "actor": actor.get("login") if isinstance(actor, dict) else str(actor),
                "forgejo_url": (
                    f"/git/{quote(owner, safe='')}/{quote(repo, safe='')}"
                    f"/actions/runs/{run_number}"
                ),
                "can_cancel": status
                in {
                    "waiting",
                    "queued",
                    "running",
                    "in_progress",
                    "blocked",
                },
                "can_approve": bool(item.get("need_approval")),
                "can_rerun": status
                in {
                    "success",
                    "failure",
                    "cancelled",
                    "timed_out",
                },
                "approval_url": _pull_request_approval_url(owner, repo, item),
            }
        )
    result = result[:effective_limit]
    if include_pagination:
        return {
            "runs": result,
            "pagination": {
                "page": effective_page,
                "limit": effective_limit,
                "total_count": total_count,
                "total_pages": max(1, (total_count + effective_limit - 1) // effective_limit),
            },
        }
    return result


def _lookup_json(response: httpx.Response, expected_type):
    try:
        payload = response.json()
    except (ValueError, AttributeError, TypeError) as exc:
        raise PipelineError("Forgejo returned invalid lookup data.", retry_safe=True) from exc
    if not isinstance(payload, expected_type):
        raise PipelineError("Forgejo returned invalid lookup data.", retry_safe=True)
    return payload

async def _find_run(
    owner: str,
    repo: str,
    run_number: int,
    token: str,
    *,
    include_jobs: bool = False,
    reconcile_deployments: bool = True,
) -> dict:
    repo_info = await forgejo.get_repo_info(owner, repo, token)
    default_branch = repo_info.get("default_branch") or "main"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            _api_path(owner, repo, "actions/runs"),
            headers=_headers(token),
            params={"run_number": run_number, "limit": 1},
        )
        if response.status_code != 200:
            raise PipelineError(
                f"Forgejo returned HTTP {response.status_code} "
                "while locating the pipeline run.", retry_safe=True,
            )
        payload = _lookup_json(response, dict)
        api_runs = payload.get("workflow_runs") or []
        if not isinstance(api_runs, list) or any(not isinstance(run, dict) for run in api_runs):
            raise PipelineError("Forgejo returned invalid lookup data.", retry_safe=True)
        item = next(
            (
                candidate
                for candidate in api_runs
                if int(candidate.get("index_in_repo") or 0) == run_number
            ),
            None,
        )
        if item is None:
            raise PipelineError(
                "Pipeline run was not found.",
                404,
                "run_not_found",
            )

        forgejo_run_id = int(item.get("id") or 0)
        if not forgejo_run_id:
            raise PipelineError(
                "Pipeline run was not found.",
                404,
                "run_not_found",
            )
        jobs_response = await client.get(
            _api_path(
                owner,
                repo,
                f"actions/runs/{forgejo_run_id}/jobs",
            ),
            headers=_headers(token),
        )
        if jobs_response.status_code != 200:
            raise PipelineError(
                f"Forgejo returned HTTP {jobs_response.status_code} "
                "while reading pipeline jobs.", retry_safe=True,
            )

    jobs_payload = _lookup_json(jobs_response, (dict, list))
    jobs = (
        jobs_payload
        if isinstance(jobs_payload, list)
        else jobs_payload.get("jobs") or []
    )
    status = _effective_run_status(
        str(item.get("status") or "waiting").lower(),
        jobs,
    )
    environment = _run_environment_from_jobs(
        jobs,
        {
            "event": item.get("event"),
            "event_payload": item.get("event_payload"),
            "head_branch": item.get("prettyref"),
            "display_title": item.get("title"),
        },
        default_branch,
    )
    deployed_revision = ""
    if (
        reconcile_deployments
        and environment == "production"
        and status == "success"
    ):
        deployed_revision = await _reconcile_production_revision(
            owner,
            repo,
            item,
            jobs,
            run_number=run_number,
            token=token,
        )
    actor = item.get("trigger_user") or {}
    result = {
        "id": run_number,
        "forgejo_run_id": forgejo_run_id,
        "name": str(item.get("workflow_id") or "Pipeline"),
        "head_branch": str(item.get("prettyref") or ""),
        "head_sha": str(item.get("commit_sha") or ""),
        "event": str(
            item.get("event")
            or ("workflow_dispatch" if item.get("event_payload") else "")
        ),
        "event_payload": str(item.get("event_payload") or ""),
        "deployed_revision": deployed_revision
        or _deployed_revision(
            {
                "event_payload": item.get("event_payload"),
                "head_sha": item.get("commit_sha"),
            }
        ),
        "display_title": str(
            item.get("title") or item.get("workflow_id") or "Pipeline"
        ),
        "status": status,
        "run_started_at": item.get("started"),
        "updated_at": (
            item.get("updated_at")
            or item.get("updated")
            or item.get("stopped")
            or item.get("started")
        ),
        "environment": environment,
        "environment_url": None,
        "deployment": None,
        "run_number": run_number,
        "job_count": len(jobs),
        "actor": actor.get("login") if isinstance(actor, dict) else str(actor),
        "forgejo_url": (
            f"/git/{quote(owner, safe='')}/{quote(repo, safe='')}"
            f"/actions/runs/{run_number}"
        ),
        "can_cancel": status
        in {
            "waiting",
            "queued",
            "running",
            "in_progress",
            "blocked",
        },
        "can_approve": bool(item.get("need_approval")),
        "can_rerun": status
        in {
            "success",
            "failure",
            "cancelled",
            "timed_out",
        },
        "approval_url": _pull_request_approval_url(owner, repo, item),
    }
    if include_jobs:
        result["_jobs"] = jobs
    return result


async def run_metadata(owner: str, repo: str, run_number: int, token: str) -> dict:
    """Return run and job state without reading action logs or derived steps."""
    source = await _find_run(
        owner,
        repo,
        run_number,
        token,
        include_jobs=True,
        reconcile_deployments=False,
    )
    jobs = source.pop("_jobs", [])
    return {
        "updated_at": source.get("updated_at") or source.get("run_started_at"),
        "state": {
            "run": {
                "title": source["display_title"],
                "status": source["status"],
                "canCancel": source["can_cancel"],
                "canApprove": source["can_approve"],
                "canRerun": source["can_rerun"],
                "approvalUrl": source.get("approval_url") or "",
                "done": not source["can_cancel"],
                "forgejoRunId": source["forgejo_run_id"],
            }
        },
        "jobs": [
            {
                "id": index,
                "forgejo_job_id": int(item.get("id") or 0),
                "name": str(item.get("name") or f"Job {index + 1}"),
                "status": str(item.get("status") or "waiting").lower(),
                "conclusion": item.get("conclusion"),
                "started": item.get("started"),
                "stopped": item.get("stopped"),
            }
            for index, item in enumerate(jobs)
            if isinstance(item, dict)
        ],
    }


def _log_redaction_values(owner: str, repo: str) -> tuple[str, ...]:
    try:
        settings = space_environment.build_settings(owner, repo)
    except Exception:
        return ()
    return tuple(
        value
        for item in settings.values()
        if len(value := str(item.get("value") or "")) >= 3
    )


def _redact_log_text(text: str, values: tuple[str, ...]) -> str:
    redacted = _ANSI.sub("", text)
    for value in values:
        redacted = redacted.replace(value, "***")
    return redacted


def _parse_log_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_duration(started: datetime | None, stopped: datetime | None) -> str:
    if not started or not stopped or stopped < started:
        return ""
    total_seconds = max(0, int(round((stopped - started).total_seconds())))
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _duration_from_logs(lines: list[dict]) -> str:
    timestamps = [
        parsed
        for line in lines
        if (parsed := _parse_log_timestamp(line.get("timestamp"))) is not None
    ]
    if not timestamps:
        return ""
    return _format_duration(timestamps[0], timestamps[-1])


def _runner_from_logs(lines: list[dict]) -> str:
    for line in lines[:20]:
        match = _RUNNER_LINE.match(str(line.get("message") or ""))
        if match:
            return f"{match.group('name')} · {match.group('version')}"
    return ""


def _log_step_event(message: str) -> tuple[str, str] | None:
    summary = ""
    status = ""
    if "⭐ Run " in message:
        summary = message.split("⭐ Run ", 1)[1].strip()
        status = "running"
    elif "✅  Success - " in message:
        summary = message.split("✅  Success - ", 1)[1].strip()
        status = "success"
    elif "✅ Success - " in message:
        summary = message.split("✅ Success - ", 1)[1].strip()
        status = "success"
    elif "❌  Failure - " in message:
        summary = message.split("❌  Failure - ", 1)[1].strip()
        status = "failure"
    elif "❌ Failure - " in message:
        summary = message.split("❌ Failure - ", 1)[1].strip()
        status = "failure"
    if not summary:
        return None
    return summary[:MAX_JOB_LOG_STEP_SUMMARY_CHARS], status


def _steps_from_log(lines: list[dict], job_status: str = "") -> list[dict]:
    steps: list[dict] = []
    positions: dict[str, int] = {}
    for line in lines:
        message = str(line.get("message") or "")
        event = _log_step_event(message)
        if event is None:
            continue
        summary, status = event
        key = summary.casefold()
        if key in positions:
            step = steps[positions[key]]
            step["status"] = status
            step["duration"] = _format_duration(
                step.get("_started_at"),
                _parse_log_timestamp(line.get("timestamp")),
            )
        else:
            if len(steps) >= MAX_JOB_LOG_STEPS:
                continue
            positions[key] = len(steps)
            steps.append(
                {
                    "summary": summary,
                    "status": status,
                    "duration": "",
                    "_started_at": _parse_log_timestamp(line.get("timestamp")),
                }
            )
    final_status = str(job_status or "").lower()
    if final_status in {"success", "failure", "cancelled", "timed_out"}:
        replacement = "failure" if final_status == "timed_out" else final_status
        stopped = next(
            (
                parsed
                for line in reversed(lines)
                if (parsed := _parse_log_timestamp(line.get("timestamp"))) is not None
            ),
            None,
        )
        for step in steps:
            if step["status"] == "running":
                step["status"] = replacement
                step["duration"] = _format_duration(step.get("_started_at"), stopped)
    for step in steps:
        step.pop("_started_at", None)
    return steps


async def _iter_bounded_log_lines(
    response: httpx.Response,
):
    """Yield decoded log lines without buffering an unbounded line or body."""
    pending = bytearray()
    truncated = False
    async for chunk in response.aiter_bytes(chunk_size=JOB_LOG_CHUNK_BYTES):
        view = memoryview(chunk)
        start = 0
        while start < len(view):
            newline = chunk.find(b"\n", start)
            end = len(view) if newline < 0 else newline
            segment = view[start:end]
            if not truncated:
                remaining = MAX_JOB_LOG_LINE_BYTES - len(pending)
                if remaining > 0:
                    pending.extend(segment[:remaining])
                if len(segment) > remaining:
                    truncated = True
            if newline < 0:
                break
            if pending.endswith(b"\r"):
                pending.pop()
            line = pending.decode("utf-8", errors="replace")
            if truncated:
                line += " … [line truncated]"
            yield line
            pending.clear()
            truncated = False
            start = newline + 1
    if pending or truncated:
        if pending.endswith(b"\r"):
            pending.pop()
        line = pending.decode("utf-8", errors="replace")
        if truncated:
            line += " … [line truncated]"
        yield line


async def _scan_job_log(
    response: httpx.Response,
    redaction_values: tuple[str, ...],
    job_status: str,
) -> dict:
    tail: deque[tuple[dict, int]] = deque()
    tail_bytes = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    runner = ""
    steps: list[dict] = []
    step_positions: dict[str, int] = {}
    line_index = 0

    async for raw_line in _iter_bounded_log_lines(response):
        match = _LOG_LINE.match(raw_line)
        timestamp = match.group("timestamp") if match else None
        message = match.group("message") if match else raw_line
        message = _redact_log_text(message, redaction_values)
        line = {
            "step": 0,
            "index": line_index,
            "timestamp": timestamp,
            "message": message,
        }
        retained_bytes = len(message.encode("utf-8")) + len(timestamp or "") + 32
        tail.append((line, retained_bytes))
        tail_bytes += retained_bytes
        while (
            len(tail) > MAX_JOB_LOG_LINES
            or tail_bytes > MAX_JOB_LOG_TAIL_BYTES
        ):
            _, removed_bytes = tail.popleft()
            tail_bytes -= removed_bytes

        parsed_timestamp = _parse_log_timestamp(timestamp)
        if parsed_timestamp is not None:
            if first_timestamp is None:
                first_timestamp = parsed_timestamp
            last_timestamp = parsed_timestamp
        if not runner and line_index < 20:
            runner_match = _RUNNER_LINE.match(message)
            if runner_match:
                runner = (
                    f"{runner_match.group('name')} · "
                    f"{runner_match.group('version')}"
                )
        event = _log_step_event(message)
        if event is not None:
            summary, status = event
            key = summary.casefold()
            if key in step_positions:
                step = steps[step_positions[key]]
                step["status"] = status
                step["duration"] = _format_duration(
                    step.get("_started_at"),
                    parsed_timestamp,
                )
            elif len(steps) < MAX_JOB_LOG_STEPS:
                step_positions[key] = len(steps)
                steps.append(
                    {
                        "summary": summary,
                        "status": status,
                        "duration": "",
                        "_started_at": parsed_timestamp,
                    }
                )
        line_index += 1

    final_status = str(job_status or "").lower()
    if final_status in {"success", "failure", "cancelled", "timed_out"}:
        replacement = "failure" if final_status == "timed_out" else final_status
        for step in steps:
            if step["status"] == "running":
                step["status"] = replacement
                step["duration"] = _format_duration(
                    step.get("_started_at"),
                    last_timestamp,
                )
    for step in steps:
        step.pop("_started_at", None)
    return {
        "duration": _format_duration(first_timestamp, last_timestamp),
        "runner": runner,
        "steps": steps,
        "logs": [line for line, _size in tail],
    }


async def run_detail(owner: str, repo: str, run_number: int, token: str) -> dict:
    source = await _find_run(owner, repo, run_number, token)
    run_id = source["forgejo_run_id"]
    redaction_values = await asyncio.to_thread(
        _log_redaction_values,
        owner,
        repo,
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        jobs_response = await client.get(
            _api_path(owner, repo, f"actions/runs/{run_id}/jobs"),
            headers=_headers(token),
        )
        if jobs_response.status_code == 404:
            raise PipelineError("Pipeline run was not found.", 404, "run_not_found")
        if jobs_response.status_code != 200:
            raise PipelineError(
                f"Forgejo returned HTTP {jobs_response.status_code} "
                "while reading pipeline jobs."
            )
        payload = jobs_response.json()
        jobs = payload if isinstance(payload, list) else payload.get("jobs") or []
        job_details: list[dict] = []
        for job_index, job in enumerate(jobs):
            log_summary = {
                "duration": "",
                "runner": "",
                "steps": [],
                "logs": [],
            }
            async with client.stream(
                "GET",
                _api_path(
                    owner,
                    repo,
                    f"actions/jobs/{int(job.get('id') or 0)}/logs",
                ),
                headers=_headers(token),
            ) as log_response:
                if log_response.status_code == 200:
                    log_summary = await _scan_job_log(
                        log_response,
                        redaction_values,
                        str(
                            job.get("conclusion")
                            or job.get("status")
                            or ""
                        ),
                    )
            job_details.append(
                {
                    **job,
                    "id": job_index,
                    "forgejo_job_id": job.get("id"),
                    **log_summary,
                }
            )
    return {
        "updated_at": source.get("updated_at") or source.get("run_started_at"),
        "state": {
            "run": {
                "title": source["display_title"],
                "status": source["status"],
                "canCancel": source["can_cancel"],
                "canApprove": source["can_approve"],
                "canRerun": source["can_rerun"],
                "approvalUrl": source.get("approval_url"),
                "done": not source["can_cancel"],
                "forgejoRunId": run_id,
            }
        },
        "jobs": job_details,
    }


async def sync_build_setting(
    owner: str,
    repo: str,
    item: dict,
    token: str,
    *,
    prior_write: bool = False,
) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        name = str(item["name"])
        encoded_name = quote(name, safe="")
        if item["kind"] == "secret":
            try:
                response = await client.put(
                    _api_path(owner, repo, f"actions/secrets/{encoded_name}"),
                    headers=_headers(token),
                    json={"data": item["value"]},
                )
            except httpx.HTTPError as exc:
                raise PipelineError(
                    "Forgejo build secret outcome is unknown.", retry_safe=False,
                ) from exc
        else:
            url = _api_path(owner, repo, f"actions/variables/{encoded_name}")
            try:
                current = await client.get(url, headers=_headers(token))
            except httpx.HTTPError as exc:
                raise PipelineError(
                    "Could not inspect the Forgejo build variable.",
                    retry_safe=not prior_write,
                ) from exc
            method = client.put if current.status_code == 200 else client.post
            try:
                response = await method(
                    url,
                    headers=_headers(token),
                    json={"value": item["value"]},
                )
            except httpx.HTTPError as exc:
                raise PipelineError(
                    "Forgejo build variable outcome is unknown.",
                    retry_safe=False,
                ) from exc
        if response.status_code not in (200, 201, 204):
            raise PipelineError(
                f"Forgejo returned HTTP {response.status_code} while syncing {name}.",
                retry_safe=(400 <= response.status_code < 500 and not prior_write),
            )
    return {
        "name": name,
        "kind": item["kind"],
        "scope": item["scope"],
    }


async def sync_build_settings(owner: str, repo: str, token: str) -> list[dict]:
    try:
        settings = await asyncio.to_thread(
            space_environment.build_settings, owner, repo,
        )
    except Exception as exc:
        raise PipelineError(
            "Could not read Space build settings.",
            retry_safe=True,
        ) from exc
    synced: list[dict] = []
    for name, item in settings.items():
        synced.append(
            await sync_build_setting(
                owner,
                repo,
                {
                    **item,
                    "name": name,
                },
                token,
                prior_write=bool(synced),
            )
        )
    return synced


async def remove_build_setting(
    owner: str,
    repo: str,
    name: str,
    kind: str,
    token: str,
) -> None:
    category = "secrets" if kind == "secret" else "variables"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.delete(
                _api_path(owner, repo, f"actions/{category}/{quote(name, safe='')}"),
                headers=_headers(token),
            )
    except httpx.HTTPError as exc:
        raise PipelineError(
            "Forgejo build setting removal outcome is unknown.", retry_safe=False,
        ) from exc
    if response.status_code not in (200, 201, 204, 404):
        raise PipelineError(
            f"Forgejo returned HTTP {response.status_code} while removing {name}."
        )


async def dispatch(
    owner: str,
    repo: str,
    workflow: str,
    ref: str,
    environment: str,
    inputs: dict[str, str],
    token: str,
    actor: str,
    *,
    audit_action: str = "dispatch",
    source_run_number: int | None = None,
) -> dict:
    if environment not in PIPELINE_ENVIRONMENTS:
        raise PipelineError(
            "environment must be preview, staging, or production",
            422,
            "invalid_environment",
        )
    workflow_name = quote(Path(workflow).name, safe="")
    payload_inputs = {
        key: str(value)
        for key, value in inputs.items()
        if key and value is not None
    }
    runner = payload_inputs.get("runner", "node20")
    if runner not in PIPELINE_RUNNER_TARGETS:
        raise PipelineError(
            "runner must be node20 or gpu",
            422,
            "invalid_runner",
        )
    runner_targets = await list_runner_targets(owner, repo, token)
    target = next(
        (item for item in runner_targets if item["value"] == runner),
        None,
    )
    if target and target.get("available") is False:
        raise PipelineError(
            f"No online Forgejo Actions runner advertises the {runner} label.",
            409,
            "runner_unavailable",
        )
    synced = await sync_build_settings(owner, repo, token)
    payload_inputs["runner"] = runner
    payload_inputs["environment"] = environment
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                _api_path(owner, repo, f"actions/workflows/{workflow_name}/dispatches"),
                headers=_headers(token), json={"ref": ref, "inputs": payload_inputs},
            )
    except httpx.HTTPError as exc:
        raise PipelineError("Pipeline dispatch outcome is unknown.", retry_safe=False) from exc
    if response.status_code not in (200, 201, 204):
        detail = response.text[:300]
        raise PipelineError(
            f"Forgejo returned HTTP {response.status_code} while dispatching: {detail}",
            retry_safe=response.status_code < 500 and not synced,
        )
    record_event(
        owner,
        repo,
        audit_action,
        actor,
        run_number=source_run_number,
        workflow=Path(workflow).name,
        environment=environment,
        revision=payload_inputs.get("revision") or ref,
    )
    return {
        "status": "queued",
        "workflow": Path(workflow).name,
        "ref": ref,
        "environment": environment,
        "synced_settings": synced,
    }


def _native_run_action_url(owner: str, repo: str, path: str) -> str:
    return (
        f"/git/{quote(owner, safe='')}/{quote(repo, safe='')}/"
        f"actions/{path.lstrip('/')}"
    )


async def run_action(
    owner: str,
    repo: str,
    run_number: int,
    action: str,
    token: str,
    actor: str,
) -> dict:
    if action not in ("cancel", "rerun", "approve", "rollback"):
        raise PipelineError("Unsupported pipeline action.", 404, "unsupported_action")
    try:
        source = await _find_run(owner, repo, run_number, token)
    except (forgejo.ForgejoError, httpx.HTTPError, ValueError, AttributeError, TypeError) as exc:
        raise PipelineError("Could not locate the pipeline run.", retry_safe=True) from exc
    if action == "rollback":
        if (
            str(source.get("status")) != "success"
            or source.get("environment") != "production"
        ):
            raise PipelineError(
                "Rollback requires a successful production pipeline run.",
                409,
                "rollback_source_invalid",
            )
    if action == "cancel":
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    _api_path(owner, repo, f"actions/runs/{source['forgejo_run_id']}/cancel"),
                    headers=_headers(token),
                )
        except httpx.HTTPError as exc:
            raise PipelineError("Pipeline cancellation outcome is unknown.", retry_safe=False) from exc
        if response.status_code == 404:
            raise PipelineError(
                "Pipeline run was not found.", 404, "run_not_found"
            )
        if response.status_code not in (200, 201, 204):
            raise PipelineError(
                f"Forgejo returned HTTP {response.status_code} while cancelling.",
                retry_safe=response.status_code < 500,
            )
        record_event(
            owner,
            repo,
            action,
            actor,
            run_number=run_number,
        )
        return {
            "status": "accepted",
            "action": action,
            "run_number": run_number,
        }

    if action == "approve":
        approval_url = source.get("approval_url")
        if not source.get("can_approve") or not approval_url:
            raise PipelineError(
                "This run is not waiting for pull-request trust approval.",
                409,
                "run_not_awaiting_approval",
            )
        record_event(
            owner,
            repo,
            "approval_review_opened",
            actor,
            run_number=run_number,
        )
        return {
            "status": "review_required",
            "action": action,
            "run_number": run_number,
            "approval_url": approval_url,
        }

    if action == "rerun":
        if not source.get("can_rerun"):
            raise PipelineError(
                "This pipeline run cannot be rerun.",
                409,
                "run_not_rerunnable",
            )
        record_event(
            owner,
            repo,
            "native_rerun_requested",
            actor,
            run_number=run_number,
        )
        return {
            "status": "native_action_required",
            "action": action,
            "run_number": run_number,
            "native_action_url": _native_run_action_url(
                owner,
                repo,
                f"runs/{run_number}/rerun",
            ),
            "method": "POST",
        }

    try:
        repo_info = await forgejo.get_repo_info(owner, repo, token)
        if not isinstance(repo_info, dict):
            raise ValueError("Forgejo returned an invalid repository response")
    except (forgejo.ForgejoError, httpx.HTTPError, ValueError, AttributeError) as exc:
        raise PipelineError("Could not resolve rollback target.", retry_safe=True) from exc
    environment = "production"
    inputs = {
        "revision": _deployed_revision(source),
        "approve_production": "true",
    }
    result = await dispatch(
        owner,
        repo,
        source["name"],
        repo_info.get("default_branch") or "main",
        environment,
        inputs,
        token,
        actor,
        audit_action=action,
        source_run_number=run_number,
    )
    return {
        **result,
        "action": action,
        "run_number": run_number,
    }


async def rerun_job(
    owner: str,
    repo: str,
    run_number: int,
    job_id: int,
    token: str,
    actor: str,
) -> dict:
    source = await _find_run(owner, repo, run_number, token)
    detail = await run_detail(owner, repo, run_number, token)
    jobs = detail.get("jobs") or []
    job = next(
        (
            item
            for item in jobs
            if item.get("id") is not None and int(item["id"]) == job_id
        ),
        None,
    )
    if not job:
        raise PipelineError("Pipeline job was not found.", 404, "job_not_found")
    if str(job.get("status") or "").lower() not in {
        "failure",
        "cancelled",
        "timed_out",
    }:
        raise PipelineError(
            "Only a failed or cancelled job can be rerun.",
            409,
            "job_not_failed",
        )
    record_event(
        owner,
        repo,
        "native_rerun_job_requested",
        actor,
        run_number=run_number,
    )
    return {
        "status": "native_action_required",
        "action": "rerun_job",
        "run_number": run_number,
        "job_id": job_id,
        "native_action_url": _native_run_action_url(
            owner,
            repo,
            f"runs/{run_number}/jobs/{job_id}/rerun",
        ),
        "method": "POST",
    }


async def install_starter(
    owner: str,
    repo: str,
    token: str,
    actor: str,
) -> dict:
    repo_info = await forgejo.get_repo_info(owner, repo, token)
    branch = repo_info.get("default_branch") or "main"
    commit = await forgejo.upsert_repo_file(
        owner,
        repo,
        branch,
        PIPELINE_WORKFLOW_PATH,
        STARTER_WORKFLOW,
        "ci: add NyankoFace pipeline",
        token,
        actor,
    )
    record_event(
        owner,
        repo,
        "install",
        actor,
        workflow=Path(PIPELINE_WORKFLOW_PATH).name,
        revision=commit.get("sha"),
    )
    return {
        "status": "installed",
        "workflow": PIPELINE_WORKFLOW_PATH,
        "commit": commit,
    }


async def summary(owner: str, repo: str, token: str) -> dict:
    workflows, runs, runner_targets = await asyncio.gather(
        list_workflows(owner, repo, token),
        list_runs(owner, repo, token),
        list_runner_targets(owner, repo, token),
    )
    return {
        "workflows": workflows,
        "runs": runs,
        "audit": await asyncio.to_thread(list_audit, owner, repo),
        "environments": list(PIPELINE_ENVIRONMENTS),
        "runner_targets": runner_targets,
        "limits": {
            "api_requests_per_minute": config.PIPELINE_API_RATE_LIMIT_PER_MINUTE,
            "runner_capacity": "configured by NYANKOFACE_ACTIONS_RUNNER_CAPACITY",
            "workflow_timeout_minutes": 20,
        },
    }
