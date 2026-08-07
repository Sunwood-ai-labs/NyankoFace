import asyncio
import hashlib
import io
import json
import os
import tarfile
import threading
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

import config
import forgejo
import main
import preview_artifacts


def run(coro):
    return asyncio.run(coro)


def opened_asset(path: Path):
    stream = path.open("rb")
    return stream, path, os.fstat(stream.fileno())


async def read_streaming_response(response: StreamingResponse) -> bytes:
    content = bytearray()
    async for chunk in response.body_iterator:
        content.extend(chunk)
    return bytes(content)


def artifact_zip(
    *,
    files: dict[str, bytes] | None = None,
    repository: str = "acme/site",
    sha: str = "abc123",
    run_id: int | str = 71,
    run_number: int | str = 9,
    tamper_digest: bool = False,
    special_member: tarfile.TarInfo | None = None,
) -> bytes:
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as archive:
        root = tarfile.TarInfo(".")
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        archive.addfile(root)
        for name, content in (files or {"index.html": b"<h1>Preview</h1>"}).items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(content))
        if special_member is not None:
            archive.addfile(special_member)
    site = tar_buffer.getvalue()
    digest = hashlib.sha256(site).hexdigest()
    manifest = {
        "schema": 1,
        "repository": repository,
        "sha": sha,
        "run_id": run_id,
        "run_number": run_number,
        "event": "pull_request",
        "artifact": preview_artifacts.ARCHIVE_NAME,
        "artifact_sha256": "0" * 64 if tamper_digest else digest,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        archive.writestr(
            f".nyankoface-artifacts/{preview_artifacts.ARCHIVE_NAME}",
            site,
        )
        archive.writestr(
            f".nyankoface-artifacts/{preview_artifacts.MANIFEST_NAME}",
            json.dumps(manifest),
        )
    return output.getvalue()


def deletion_artifact_zip(
    *,
    repository: str = "acme/site",
    sha: str = "d" * 40,
    run_id: int | str = 71,
    run_number: int | str = 9,
    operation: str = "delete",
    include_site: bool = False,
    environment: str = "staging",
) -> bytes:
    manifest = {
        "schema": 1,
        "repository": repository,
        "sha": sha,
        "run_id": run_id,
        "run_number": run_number,
        "event": "workflow_dispatch",
        "environment": environment,
        "operation": operation,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        archive.writestr(
            f".nyankoface-artifacts/{preview_artifacts.MANIFEST_NAME}",
            json.dumps(manifest),
        )
        if include_site:
            archive.writestr(
                f".nyankoface-artifacts/{preview_artifacts.ARCHIVE_NAME}",
                b"unexpected-site",
            )
    return output.getvalue()


def zip_with_many_empty_entries(
    count: int,
    *,
    comment: bytes = b"",
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        for index in range(count):
            archive.writestr(f"empty-{index}.txt", b"")
        archive.comment = comment
    return output.getvalue()


def zip_with_long_names(count: int, name_length: int) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        for index in range(count):
            suffix = f"-{index}.txt"
            archive.writestr(
                f"{'x' * (name_length - len(suffix))}{suffix}",
                b"",
            )
    return output.getvalue()


def with_declared_zip_entry_count(content: bytes, count: int) -> bytes:
    patched = bytearray(content)
    end_record = patched.rfind(b"PK\x05\x06")
    assert end_record >= 0
    patched[end_record + 8 : end_record + 10] = count.to_bytes(2, "little")
    patched[end_record + 10 : end_record + 12] = count.to_bytes(2, "little")
    return bytes(patched)


def publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes) -> dict:
    monkeypatch.setattr(config, "PIPELINE_DATA_DIR", str(tmp_path))
    return preview_artifacts.publish(
        owner="acme",
        repo="site",
        environment="preview",
        key="pr-4",
        artifact_zip=content,
        expected_repository="acme/site",
        expected_sha="abc123",
        expected_run_id=71,
        expected_run_number=9,
        artifact_id=5,
    )


def publish_pr_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_number: int,
) -> dict:
    revision = f"{run_number:040x}"
    monkeypatch.setattr(config, "PIPELINE_DATA_DIR", str(tmp_path))
    return preview_artifacts.publish(
        owner="acme",
        repo="site",
        environment="preview",
        key="pr-4",
        artifact_zip=artifact_zip(
            sha=revision,
            run_number=run_number,
        ),
        expected_repository="acme/site",
        expected_sha=revision,
        expected_run_id=71,
        expected_run_number=run_number,
        artifact_id=5,
    )


def test_zip_entry_limit_is_enforced_before_zipfile_parses_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = zip_with_many_empty_entries(
        preview_artifacts.MAX_ZIP_ENTRIES + 1
    )
    monkeypatch.setattr(
        preview_artifacts.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: pytest.fail(
            "ZipFile must not parse an oversized central directory"
        ),
    )

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="too many entries",
    ):
        preview_artifacts.source_sha(
            content,
            expected_repository="acme/site",
            expected_run_id=71,
            expected_run_number=9,
        )


@pytest.mark.parametrize(
    "entrypoint",
    ("source_sha", "deletion_source_sha", "publish"),
)
def test_forged_low_zip_entry_count_is_rejected_at_every_entrypoint(
    entrypoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = with_declared_zip_entry_count(
        zip_with_many_empty_entries(
            preview_artifacts.MAX_ZIP_ENTRIES + 1
        ),
        1,
    )
    monkeypatch.setattr(
        preview_artifacts.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: pytest.fail(
            "ZipFile must not parse a forged central directory"
        ),
    )

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="too many entries",
    ):
        if entrypoint == "source_sha":
            preview_artifacts.source_sha(
                content,
                expected_repository="acme/site",
                expected_run_id=71,
                expected_run_number=9,
            )
        elif entrypoint == "deletion_source_sha":
            preview_artifacts.deletion_source_sha(
                content,
                expected_repository="acme/site",
                expected_run_id=71,
                expected_run_number=9,
                expected_environment="staging",
            )
        else:
            preview_artifacts.publish(
                owner="acme",
                repo="site",
                environment="preview",
                key="pr-4",
                artifact_zip=content,
                expected_repository="acme/site",
                expected_sha="abc123",
                expected_run_id=71,
                expected_run_number=9,
                artifact_id=5,
            )


def test_zip_central_directory_byte_limit_is_enforced_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = zip_with_long_names(5, 60_000)
    monkeypatch.setattr(
        preview_artifacts.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: pytest.fail(
            "ZipFile must not parse an oversized central directory"
        ),
    )

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="central directory exceeds",
    ):
        preview_artifacts.source_sha(
            content,
            expected_repository="acme/site",
            expected_run_id=71,
            expected_run_number=9,
        )


def test_zip_entry_limit_boundary_and_declared_count_mismatch() -> None:
    preview_artifacts._preflight_zip(
        zip_with_many_empty_entries(preview_artifacts.MAX_ZIP_ENTRIES)
    )
    content = with_declared_zip_entry_count(
        zip_with_many_empty_entries(2),
        1,
    )

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="entry count is invalid",
    ):
        preview_artifacts._preflight_zip(content)


def test_final_eocd_signature_in_comment_is_rejected_before_zipfile_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = zip_with_many_empty_entries(
        1,
        comment=b"comment-PK\x05\x06" + (b"\x00" * 22),
    )
    monkeypatch.setattr(
        preview_artifacts.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: pytest.fail(
            "ZipFile must not select a different EOCD record"
        ),
    )

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="end record is invalid",
    ):
        preview_artifacts.source_sha(
            content,
            expected_repository="acme/site",
            expected_run_id=71,
            expected_run_number=9,
        )


def test_zip64_locator_is_rejected_without_legacy_sentinels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = zip_with_many_empty_entries(0)
    end_record = content.rfind(b"PK\x05\x06")
    assert end_record == 0
    locator = b"PK\x06\x07" + (b"\x00" * 16)
    content = locator + content
    monkeypatch.setattr(
        preview_artifacts.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: pytest.fail(
            "ZipFile must not apply a ZIP64 locator override"
        ),
    )

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="ZIP64",
    ):
        preview_artifacts.source_sha(
            content,
            expected_repository="acme/site",
            expected_run_id=71,
            expected_run_number=9,
        )


def test_zip64_end_record_is_rejected_before_zipfile_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = bytearray(artifact_zip())
    end_record = content.rfind(b"PK\x05\x06")
    assert end_record >= 0
    content[end_record + 8 : end_record + 12] = b"\xff\xff\xff\xff"
    monkeypatch.setattr(
        preview_artifacts.zipfile,
        "ZipFile",
        lambda *_args, **_kwargs: pytest.fail(
            "ZipFile must not parse a ZIP64 central directory"
        ),
    )

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="ZIP64",
    ):
        preview_artifacts.source_sha(
            bytes(content),
            expected_repository="acme/site",
            expected_run_id=71,
            expected_run_number=9,
        )


def test_verified_artifact_is_published_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = publish(tmp_path, monkeypatch, artifact_zip())

    index = preview_artifacts.asset_path(
        "acme", "site", "preview", "pr-4", "index.html"
    )
    assert index is not None
    assert index.read_text(encoding="utf-8") == "<h1>Preview</h1>"
    assert result["artifact_id"] == 5
    assert len(result["artifact_sha256"]) == 64
    assert preview_artifacts.metadata(
        "acme", "site", "preview", "pr-4"
    ) == result


def test_pr_preview_close_watermark_blocks_old_publish_and_allows_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "PIPELINE_DATA_DIR", str(tmp_path))
    closed = preview_artifacts.mark_preview_closed(
        "acme",
        "site",
        "pr-4",
        run_number=10,
    )
    assert closed["advanced"] is True
    assert closed["removed"] is False

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="state watermark",
    ):
        publish_pr_run(
            tmp_path,
            monkeypatch,
            run_number=9,
        )

    published = publish_pr_run(
        tmp_path,
        monkeypatch,
        run_number=11,
    )
    assert published["run_number"] == 11
    assert preview_artifacts.asset_path(
        "acme",
        "site",
        "preview",
        "pr-4",
        "index.html",
    ) is not None

    stale = preview_artifacts.mark_preview_closed(
        "acme",
        "site",
        "pr-4",
        run_number=10,
    )
    assert stale["advanced"] is False
    assert stale["removed"] is False
    assert preview_artifacts.metadata(
        "acme",
        "site",
        "preview",
        "pr-4",
    )["run_number"] == 11
    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="state watermark",
    ):
        publish_pr_run(
            tmp_path,
            monkeypatch,
            run_number=9,
        )


def test_pr_preview_close_wins_against_inflight_older_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "PIPELINE_DATA_DIR", str(tmp_path))
    extracted = threading.Event()
    release = threading.Event()
    original_extract = preview_artifacts._extract_site
    errors: list[Exception] = []

    def blocking_extract(content: bytes, destination: Path) -> None:
        original_extract(content, destination)
        extracted.set()
        assert release.wait(timeout=5)

    def publish_old() -> None:
        try:
            publish_pr_run(
                tmp_path,
                monkeypatch,
                run_number=9,
            )
        except Exception as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    monkeypatch.setattr(
        preview_artifacts,
        "_extract_site",
        blocking_extract,
    )
    worker = threading.Thread(target=publish_old)
    worker.start()
    assert extracted.wait(timeout=5)

    transition = preview_artifacts.mark_preview_closed(
        "acme",
        "site",
        "pr-4",
        run_number=10,
    )
    assert transition["advanced"] is True
    assert transition["removed"] is False
    release.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], preview_artifacts.PreviewArtifactError)
    assert preview_artifacts.asset_path(
        "acme",
        "site",
        "preview",
        "pr-4",
        "index.html",
    ) is None


def test_pr_preview_close_is_idempotent_and_fail_closed_on_bad_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish_pr_run(tmp_path, monkeypatch, run_number=12)
    first = preview_artifacts.mark_preview_closed(
        "acme",
        "site",
        "pr-4",
        run_number=13,
    )
    second = preview_artifacts.mark_preview_closed(
        "acme",
        "site",
        "pr-4",
        run_number=13,
    )
    assert first["advanced"] is True
    assert first["removed"] is True
    assert second["advanced"] is False
    assert second["removed"] is False

    state_path = preview_artifacts._preview_state_path(
        "acme",
        "site",
        "pr-4",
    )
    state_path.write_text("{broken", encoding="utf-8")
    assert preview_artifacts.asset_path(
        "acme",
        "site",
        "preview",
        "pr-4",
        "index.html",
    ) is None
    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="state is invalid",
    ):
        publish_pr_run(tmp_path, monkeypatch, run_number=14)


def test_forgejo_string_run_metadata_is_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = publish(
        tmp_path,
        monkeypatch,
        artifact_zip(run_id="71", run_number="9"),
    )

    assert result["run_id"] == 71
    assert result["run_number"] == 9


def test_manual_preview_pruning_applies_ttl_count_and_protection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "PIPELINE_DATA_DIR", str(tmp_path))

    def create_preview(
        key: str,
        run_number: int,
        published_at: int,
        *,
        valid: bool = True,
    ) -> Path:
        path = preview_artifacts.deployment_path(
            "acme",
            "site",
            "preview",
            key,
        )
        path.mkdir(parents=True)
        metadata = {
            "owner": "acme",
            "repo": "site",
            "environment": "preview",
            "key": key,
            "run_number": run_number,
            "published_at": published_at,
        }
        if not valid:
            metadata["repo"] = "different"
        (path / ".nyankoface-deployment.json").write_text(
            json.dumps(metadata),
            encoding="utf-8",
        )
        return path

    protected = create_preview("run-1", 1, 1)
    over_limit = create_preview("run-2", 2, 90)
    newest = create_preview("run-3", 3, 95)
    malformed = create_preview("run-4", 4, 1, valid=False)
    pull_request = create_preview("pr-4", 4, 1)

    removed = preview_artifacts.prune_run_previews(
        "acme",
        "site",
        protected_keys=("run-1",),
        now=100,
        retention_seconds=20,
        max_count=1,
    )

    assert removed == ["run-2"]
    assert protected.is_dir()
    assert newest.is_dir()
    assert malformed.is_dir()
    assert pull_request.is_dir()
    assert not over_limit.exists()


def test_manual_preview_pruning_uses_legacy_metadata_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "PIPELINE_DATA_DIR", str(tmp_path))
    path = preview_artifacts.deployment_path(
        "acme",
        "site",
        "preview",
        "run-9",
    )
    path.mkdir(parents=True)
    metadata_path = path / ".nyankoface-deployment.json"
    metadata_path.write_text(
        json.dumps(
            {
                "owner": "acme",
                "repo": "site",
                "environment": "preview",
                "key": "run-9",
                "run_number": 9,
            }
        ),
        encoding="utf-8",
    )
    os.utime(metadata_path, (10, 10))

    assert preview_artifacts.prune_run_previews(
        "acme",
        "site",
        now=100,
        retention_seconds=20,
        max_count=10,
    ) == ["run-9"]
    assert not path.exists()


def test_manifest_digest_and_run_metadata_are_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="SHA-256",
    ):
        publish(
            tmp_path,
            monkeypatch,
            artifact_zip(tamper_digest=True),
        )
    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="does not match",
    ):
        publish(
            tmp_path,
            monkeypatch,
            artifact_zip(run_id=72),
        )
    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="run_id is invalid",
    ):
        publish(
            tmp_path,
            monkeypatch,
            artifact_zip(run_id="71.0"),
        )


def test_source_sha_comes_from_the_workflow_artifact_manifest() -> None:
    revision = "a" * 40
    content = artifact_zip(sha=revision)

    assert (
        preview_artifacts.source_sha(
            content,
            expected_repository="acme/site",
            expected_run_id=71,
            expected_run_number=9,
        )
        == revision
    )

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="does not match",
    ):
        preview_artifacts.source_sha(
            content,
            expected_repository="other/site",
            expected_run_id=71,
            expected_run_number=9,
        )


def test_staging_deletion_marker_requires_exact_authenticated_run() -> None:
    revision = "d" * 40
    content = deletion_artifact_zip(sha=revision)

    assert (
        preview_artifacts.deletion_source_sha(
            content,
            expected_repository="acme/site",
            expected_run_id=71,
            expected_run_number=9,
            expected_environment="staging",
        )
        == revision
    )
    assert (
        preview_artifacts.deletion_source_sha(
            deletion_artifact_zip(operation="publish"),
            expected_repository="acme/site",
            expected_run_id=71,
            expected_run_number=9,
            expected_environment="staging",
        )
        is None
    )

    for invalid in (
        deletion_artifact_zip(repository="other/site"),
        deletion_artifact_zip(run_id=72),
        deletion_artifact_zip(run_number=10),
        deletion_artifact_zip(include_site=True),
    ):
        with pytest.raises(
            preview_artifacts.PreviewArtifactError,
            match="does not match",
        ):
            preview_artifacts.deletion_source_sha(
                invalid,
                expected_repository="acme/site",
                expected_run_id=71,
                expected_run_number=9,
                expected_environment="staging",
            )


def test_preview_deletion_marker_retires_site_and_blocks_older_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = publish_pr_run(
        tmp_path,
        monkeypatch,
        run_number=9,
    )
    revision = "d" * 40
    marker = deletion_artifact_zip(
        sha=revision,
        run_id=72,
        run_number=10,
        environment="preview",
    )

    assert (
        preview_artifacts.deletion_source_sha(
            marker,
            expected_repository="acme/site",
            expected_run_id=72,
            expected_run_number=10,
            expected_environment="preview",
        )
        == revision
    )
    deleted = preview_artifacts.mark_preview_deleted(
        "acme",
        "site",
        "pr-4",
        run_number=10,
        source_sha=revision,
    )
    assert published["run_number"] == 9
    assert deleted["advanced"] is True
    assert deleted["removed"] is True
    assert preview_artifacts.metadata(
        "acme", "site", "preview", "pr-4"
    ) is None

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="state watermark",
    ):
        publish_pr_run(
            tmp_path,
            monkeypatch,
            run_number=9,
        )

    reopened = publish_pr_run(
        tmp_path,
        monkeypatch,
        run_number=11,
    )
    assert reopened["run_number"] == 11
    assert preview_artifacts.asset_path(
        "acme", "site", "preview", "pr-4", "index.html"
    ) is not None


def test_preview_deletion_marker_requires_preview_environment() -> None:
    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="does not match",
    ):
        preview_artifacts.deletion_source_sha(
            deletion_artifact_zip(environment="staging"),
            expected_repository="acme/site",
            expected_run_id=71,
            expected_run_number=9,
            expected_environment="preview",
        )


def test_staging_tombstone_blocks_older_publish_and_allows_newer_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "PIPELINE_DATA_DIR", str(tmp_path))
    current = preview_artifacts.deployment_path(
        "acme",
        "site",
        "staging",
        "current",
    )
    current.mkdir(parents=True)
    (current / "index.html").write_text("stale", encoding="utf-8")

    deleted = preview_artifacts.mark_staging_deleted(
        "acme",
        "site",
        run_number=10,
        source_sha="d" * 40,
    )

    assert deleted["removed"] is True
    assert not current.exists()
    tombstone = current.parent / preview_artifacts.STAGING_TOMBSTONE_NAME
    assert json.loads(tombstone.read_text(encoding="utf-8"))["run_number"] == 10

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="older than its deletion marker",
    ):
        preview_artifacts.publish(
            owner="acme",
            repo="site",
            environment="staging",
            key="current",
            artifact_zip=artifact_zip(
                sha="a" * 40,
                run_id=72,
                run_number=9,
            ),
            expected_repository="acme/site",
            expected_sha="a" * 40,
            expected_run_id=72,
            expected_run_number=9,
            artifact_id=6,
        )

    result = preview_artifacts.publish(
        owner="acme",
        repo="site",
        environment="staging",
        key="current",
        artifact_zip=artifact_zip(
            sha="b" * 40,
            run_id=73,
            run_number=11,
        ),
        expected_repository="acme/site",
        expected_sha="b" * 40,
        expected_run_id=73,
        expected_run_number=11,
        artifact_id=7,
    )

    assert result["run_number"] == 11
    assert current.is_dir()
    assert not tombstone.exists()


@pytest.mark.parametrize(
    "member",
    [
        tarfile.TarInfo("../escape.txt"),
        tarfile.TarInfo("/absolute.txt"),
        tarfile.TarInfo("link"),
    ],
)
def test_unsafe_tar_members_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member: tarfile.TarInfo,
) -> None:
    if member.name == "link":
        member.type = tarfile.SYMTYPE
        member.linkname = "index.html"
    else:
        member.size = 0
    with pytest.raises(preview_artifacts.PreviewArtifactError):
        publish(
            tmp_path,
            monkeypatch,
            artifact_zip(special_member=member),
        )
    assert not (tmp_path / "deployments" / "escape.txt").exists()


def test_tar_member_limit_is_enforced_while_reading_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tarfile.TarInfo("empty-directory")
    directory.type = tarfile.DIRTYPE
    monkeypatch.setattr(preview_artifacts, "MAX_MEMBERS", 2)

    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="too many entries",
    ):
        publish(
            tmp_path,
            monkeypatch,
            artifact_zip(special_member=directory),
        )


def test_asset_lookup_rejects_path_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish(tmp_path, monkeypatch, artifact_zip())
    with pytest.raises(
        preview_artifacts.PreviewArtifactError,
        match="path traversal",
    ):
        preview_artifacts.asset_path(
            "acme", "site", "preview", "pr-4", "../secret"
        )


@pytest.mark.parametrize(
    ("requested", "stored"),
    [
        ("guide/pipelines", "guide/pipelines.html"),
        ("guide/", "guide/index.html"),
    ],
)
def test_asset_lookup_resolves_clean_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
    stored: str,
) -> None:
    publish(
        tmp_path,
        monkeypatch,
        artifact_zip(
            files={
                "index.html": b"<h1>Home</h1>",
                stored: b"<h1>Guide</h1>",
            }
        ),
    )

    resolved = preview_artifacts.asset_path(
        "acme", "site", "preview", "pr-4", requested
    )

    assert resolved is not None
    assert resolved.relative_to(
        preview_artifacts.deployment_path(
            "acme", "site", "preview", "pr-4"
        )
    ).as_posix() == stored


def test_open_asset_pins_an_open_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"<h1>Pinned Preview</h1>"
    publish(
        tmp_path,
        monkeypatch,
        artifact_zip(files={"index.html": content}),
    )

    opened = preview_artifacts.open_asset(
        "acme", "site", "preview", "pr-4", "index.html"
    )

    assert opened is not None
    stream, path, stat_result = opened
    try:
        assert stream.read() == content
        assert stat_result.st_size == len(content)
        assert path.name == "index.html"
    finally:
        stream.close()


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("index.html", b"<h1>Preview</h1>"),
        ("page.xhtml", b"<html xmlns='http://www.w3.org/1999/xhtml'/>"),
        ("image.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),
        ("feed.xml", b"<?xml version='1.0'?><feed/>"),
    ],
)
def test_browser_active_preview_response_is_csp_sandboxed(
    tmp_path: Path,
    filename: str,
    content: bytes,
) -> None:
    index = tmp_path / filename
    index.write_bytes(content)
    with (
        patch.object(
            forgejo,
            "get_repo_info",
            AsyncMock(return_value={"private": False}),
        ),
        patch.object(
            preview_artifacts,
            "open_asset",
            return_value=opened_asset(index),
        ),
    ):
        response = run(
            main.serve_pipeline_deployment_asset(
                "acme",
                "site",
                "preview",
                "pr-4",
                filename,
            )
        )

    assert isinstance(response, StreamingResponse)
    assert run(read_streaming_response(response)) == content
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["cache-control"] == "no-store"
    assert "sandbox allow-scripts" in response.headers["content-security-policy"]
    assert "connect-src 'none'" in response.headers["content-security-policy"]


def test_inert_preview_asset_does_not_receive_document_csp(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with (
        patch.object(
            forgejo,
            "get_repo_info",
            AsyncMock(return_value={"private": False}),
        ),
        patch.object(
            preview_artifacts,
            "open_asset",
            return_value=opened_asset(image),
        ),
    ):
        response = run(
            main.serve_pipeline_deployment_asset(
                "acme",
                "site",
                "preview",
                "pr-4",
                "image.png",
            )
        )

    assert response.media_type == "image/png"
    assert run(read_streaming_response(response)) == b"\x89PNG\r\n\x1a\n"
    assert "content-security-policy" not in response.headers


def test_preview_head_does_not_read_the_asset_body(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    content = b"<h1>Preview without buffering</h1>"
    index.write_bytes(content)
    with (
        patch.object(
            forgejo,
            "get_repo_info",
            AsyncMock(return_value={"private": False}),
        ),
        patch.object(
            preview_artifacts,
            "open_asset",
            return_value=opened_asset(index),
        ),
        patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("HEAD must not read the asset body"),
        ),
    ):
        response = run(
            main.serve_pipeline_deployment_asset(
                "acme",
                "site",
                "preview",
                "pr-4",
                "index.html",
                head_only=True,
            )
        )

    assert response.body == b""
    assert response.headers["content-length"] == str(len(content))
    assert "sandbox allow-scripts" in response.headers["content-security-policy"]


def test_private_repository_preview_is_hidden(tmp_path: Path) -> None:
    with (
        patch.object(
            forgejo,
            "get_repo_info",
            AsyncMock(return_value={"private": True}),
        ),
        patch.object(preview_artifacts, "open_asset") as asset,
    ):
        with pytest.raises(HTTPException) as error:
            run(
                main.serve_pipeline_deployment_asset(
                    "acme",
                    "secret",
                    "preview",
                    "pr-4",
                    "index.html",
                )
            )

    assert error.value.status_code == 404
    asset.assert_not_called()
