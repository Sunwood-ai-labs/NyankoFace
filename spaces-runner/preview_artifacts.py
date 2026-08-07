"""Verified static Preview and staging artifact storage.

Untrusted pull-request jobs may build and upload an artifact, but they never
receive a repository write token.  This trusted controller validates the
artifact against Forgejo run metadata before publishing it.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import struct
import tarfile
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import config

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 250 * 1024 * 1024
MAX_FILES = 20_000
MAX_MEMBERS = 20_000
MAX_ZIP_ENTRIES = 64
MAX_ZIP_CENTRAL_DIRECTORY_BYTES = 256 * 1024
MAX_PATH_LENGTH = 512
MANIFEST_NAME = "nyankoface-site-manifest.json"
ARCHIVE_NAME = "nyankoface-site.tgz"
STAGING_TOMBSTONE_NAME = ".nyankoface-staging-tombstone.json"
_publish_lock = threading.Lock()
_ASCII_INTEGER = re.compile(r"[0-9]+")
_RUN_PREVIEW_KEY = re.compile(r"run-([1-9][0-9]*)")
_PR_PREVIEW_KEY = re.compile(r"pr-([1-9][0-9]*)")
_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
_ZIP_EOCD = struct.Struct("<4s4H2LH")
_ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
_ZIP_CENTRAL_FIXED_SIZE = 46
_ZIP_CENTRAL_VARIABLE_LENGTHS = struct.Struct("<3H")
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP64_LOCATOR_SIZE = 20


class PreviewArtifactError(RuntimeError):
    """A Preview artifact failed integrity or extraction validation."""


def _manifest_integer(value: object, field: str) -> int:
    """Normalize Forgejo's string-valued Actions counters without coercion."""
    if isinstance(value, bool):
        raise PreviewArtifactError(f"Artifact manifest {field} is invalid.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _ASCII_INTEGER.fullmatch(value):
        return int(value)
    raise PreviewArtifactError(f"Artifact manifest {field} is invalid.")


def _root() -> Path:
    root = Path(config.PIPELINE_DATA_DIR) / "deployments"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_segment(value: str, label: str) -> str:
    if not value or len(value) > 120:
        raise PreviewArtifactError(f"Invalid {label}.")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._" for character in value):
        raise PreviewArtifactError(f"Invalid {label}.")
    return value


def deployment_path(
    owner: str,
    repo: str,
    environment: str,
    key: str,
) -> Path:
    if environment not in {"preview", "staging"}:
        raise PreviewArtifactError("Invalid deployment environment.")
    return (
        _root()
        / _safe_segment(owner, "owner")
        / _safe_segment(repo, "repository")
        / environment
        / _safe_segment(key, "deployment key")
    )


def _zip_member(archive: zipfile.ZipFile, basename: str) -> zipfile.ZipInfo:
    matches = [
        item
        for item in archive.infolist()
        if not item.is_dir() and PurePosixPath(item.filename).name == basename
    ]
    if len(matches) != 1:
        raise PreviewArtifactError(f"Artifact must contain exactly one {basename}.")
    return matches[0]


def _read_limited(stream: BinaryIO, limit: int) -> bytes:
    content = stream.read(limit + 1)
    if len(content) > limit:
        raise PreviewArtifactError("Artifact exceeds the configured size limit.")
    return content


def _preflight_zip(artifact_zip: bytes) -> None:
    """Bound and validate the central directory before ``ZipFile`` parses it."""
    minimum_size = _ZIP_EOCD.size
    search_start = max(0, len(artifact_zip) - (minimum_size + 65_535))
    offset = artifact_zip.rfind(_ZIP_EOCD_SIGNATURE, search_start)
    if offset < 0 or offset + minimum_size > len(artifact_zip):
        raise PreviewArtifactError("Artifact ZIP end record is invalid.")
    fields = _ZIP_EOCD.unpack_from(artifact_zip, offset)
    comment_length = int(fields[-1])
    if offset + minimum_size + comment_length != len(artifact_zip):
        # CPython selects the final EOCD signature before it interprets the
        # stored comment length. Rejecting rather than searching backward
        # prevents preflight and ZipFile from validating different records.
        raise PreviewArtifactError("Artifact ZIP end record is invalid.")
    locator_offset = offset - _ZIP64_LOCATOR_SIZE
    if (
        locator_offset >= 0
        and artifact_zip[
            locator_offset : locator_offset + len(_ZIP64_LOCATOR_SIGNATURE)
        ]
        == _ZIP64_LOCATOR_SIGNATURE
    ):
        # ZipFile lets a locator override non-sentinel legacy EOCD fields.
        # This artifact contract never needs ZIP64, so reject the locator
        # itself before constructing ZipFile.
        raise PreviewArtifactError("ZIP64 artifacts are not supported.")
    (
        _signature,
        disk_number,
        directory_disk,
        entries_on_disk,
        total_entries,
        directory_size,
        directory_offset,
        _comment_length,
    ) = fields
    if (
        disk_number != 0
        or directory_disk != 0
        or entries_on_disk != total_entries
    ):
        raise PreviewArtifactError("Multi-disk artifact ZIPs are not supported.")
    if (
        total_entries == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    ):
        raise PreviewArtifactError("ZIP64 artifacts are not supported.")
    if total_entries > MAX_ZIP_ENTRIES:
        raise PreviewArtifactError(
            "Artifact ZIP contains too many entries."
        )
    if directory_size > MAX_ZIP_CENTRAL_DIRECTORY_BYTES:
        raise PreviewArtifactError(
            "Artifact ZIP central directory exceeds the configured size limit."
        )
    directory_start = offset - directory_size
    if (
        directory_start < 0
        or directory_offset != directory_start
        or directory_offset + directory_size != offset
    ):
        raise PreviewArtifactError("Artifact ZIP central directory is invalid.")

    cursor = directory_start
    actual_entries = 0
    while cursor < offset:
        if actual_entries >= MAX_ZIP_ENTRIES:
            raise PreviewArtifactError(
                "Artifact ZIP contains too many entries."
            )
        if (
            cursor + _ZIP_CENTRAL_FIXED_SIZE > offset
            or artifact_zip[
                cursor : cursor + len(_ZIP_CENTRAL_SIGNATURE)
            ]
            != _ZIP_CENTRAL_SIGNATURE
        ):
            raise PreviewArtifactError(
                "Artifact ZIP central directory is invalid."
            )
        (
            filename_length,
            extra_length,
            comment_length,
        ) = _ZIP_CENTRAL_VARIABLE_LENGTHS.unpack_from(
            artifact_zip,
            cursor + 28,
        )
        record_size = (
            _ZIP_CENTRAL_FIXED_SIZE
            + filename_length
            + extra_length
            + comment_length
        )
        if cursor + record_size > offset:
            raise PreviewArtifactError(
                "Artifact ZIP central directory is invalid."
            )
        cursor += record_size
        actual_entries += 1

    if cursor != offset or actual_entries != total_entries:
        raise PreviewArtifactError(
            "Artifact ZIP central directory entry count is invalid."
        )


def _open_artifact_zip(artifact_zip: bytes) -> zipfile.ZipFile:
    """Open a preflighted, bounded artifact ZIP."""
    _preflight_zip(artifact_zip)
    try:
        return zipfile.ZipFile(io.BytesIO(artifact_zip))
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        OSError,
    ) as exc:
        raise PreviewArtifactError("Artifact ZIP is invalid.") from exc


def _read_artifact_manifest(
    artifact_zip: bytes,
) -> tuple[dict, zipfile.ZipFile]:
    """Open an Actions ZIP and decode its bounded manifest."""
    try:
        archive = _open_artifact_zip(artifact_zip)
        manifest_info = _zip_member(archive, MANIFEST_NAME)
        if manifest_info.file_size > 64 * 1024:
            raise PreviewArtifactError("Artifact manifest is too large.")
        with archive.open(manifest_info) as stream:
            manifest_bytes = _read_limited(stream, 64 * 1024)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise PreviewArtifactError("Artifact manifest must be an object.")
        return manifest, archive
    except (
        zipfile.BadZipFile,
        UnicodeDecodeError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        raise PreviewArtifactError("Artifact manifest is invalid.") from exc
    except Exception:
        if "archive" in locals():
            archive.close()
        raise


def source_sha(
    artifact_zip: bytes,
    *,
    expected_repository: str,
    expected_run_id: int,
    expected_run_number: int,
) -> str:
    """Read the immutable checkout SHA recorded by the successful workflow."""
    if len(artifact_zip) > MAX_ARCHIVE_BYTES:
        raise PreviewArtifactError("Artifact ZIP exceeds the configured size limit.")
    manifest, archive = _read_artifact_manifest(artifact_zip)
    archive.close()
    sha = str(manifest.get("sha") or "").lower()
    if (
        manifest.get("schema") != 1
        or manifest.get("repository") != expected_repository
        or manifest.get("artifact") != ARCHIVE_NAME
        or manifest.get("operation") == "delete"
        or not re.fullmatch(r"[0-9a-f]{40,64}", sha)
        or _manifest_integer(manifest.get("run_id"), "run_id") != expected_run_id
        or _manifest_integer(manifest.get("run_number"), "run_number")
        != expected_run_number
    ):
        raise PreviewArtifactError("Artifact manifest does not match the Forgejo run.")
    return sha


def deletion_source_sha(
    artifact_zip: bytes,
    *,
    expected_repository: str,
    expected_run_id: int,
    expected_run_number: int,
    expected_environment: str,
) -> str | None:
    """Validate an explicit deployment deletion marker, if one is present."""
    if expected_environment not in {"preview", "staging"}:
        raise PreviewArtifactError("Invalid deletion marker environment.")
    if len(artifact_zip) > MAX_ARCHIVE_BYTES:
        raise PreviewArtifactError("Artifact ZIP exceeds the configured size limit.")
    manifest, archive = _read_artifact_manifest(artifact_zip)
    try:
        contains_site = any(
            not item.is_dir()
            and PurePosixPath(item.filename).name == ARCHIVE_NAME
            for item in archive.infolist()
        )
    finally:
        archive.close()
    if manifest.get("operation") != "delete":
        return None
    sha = str(manifest.get("sha") or "").lower()
    if (
        manifest.get("schema") != 1
        or manifest.get("repository") != expected_repository
        or manifest.get("environment") != expected_environment
        or not re.fullmatch(r"[0-9a-f]{40,64}", sha)
        or _manifest_integer(manifest.get("run_id"), "run_id")
        != expected_run_id
        or _manifest_integer(manifest.get("run_number"), "run_number")
        != expected_run_number
        or manifest.get("artifact") is not None
        or manifest.get("artifact_sha256") is not None
        or contains_site
    ):
        raise PreviewArtifactError(
            "Deployment deletion marker does not match the Forgejo run."
        )
    return sha


def _safe_member_path(name: str) -> PurePosixPath:
    if "\x00" in name or len(name) > MAX_PATH_LENGTH:
        raise PreviewArtifactError("Artifact contains an invalid path.")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise PreviewArtifactError("Artifact contains a path traversal.")
    return path


def _extract_site(archive_bytes: bytes, destination: Path) -> None:
    total_bytes = 0
    file_count = 0
    member_count = 0
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        for member in archive:
            member_count += 1
            if member_count > MAX_MEMBERS:
                raise PreviewArtifactError("Artifact contains too many entries.")
            if member.isdir() and member.name in {".", "./"}:
                continue
            relative = _safe_member_path(member.name)
            if member.mode & 0o6000:
                raise PreviewArtifactError("Artifact contains a privileged file mode.")
            if not (member.isdir() or member.isreg()):
                raise PreviewArtifactError("Artifact contains a non-regular file.")
            if member.isreg():
                file_count += 1
                total_bytes += int(member.size)
                if file_count > MAX_FILES or total_bytes > MAX_EXTRACTED_BYTES:
                    raise PreviewArtifactError("Expanded artifact exceeds safety limits.")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise PreviewArtifactError("Artifact file could not be read.")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            os.chmod(target, 0o644)
    if not (destination / "index.html").is_file():
        raise PreviewArtifactError("Artifact does not contain index.html.")


def _staging_tombstone_path(owner: str, repo: str) -> Path:
    return (
        deployment_path(owner, repo, "staging", "current").parent
        / STAGING_TOMBSTONE_NAME
    )


def _preview_state_path(owner: str, repo: str, key: str) -> Path:
    if (
        _PR_PREVIEW_KEY.fullmatch(key) is None
        and _RUN_PREVIEW_KEY.fullmatch(key) is None
    ):
        raise PreviewArtifactError("Invalid preview key.")
    return (
        deployment_path(owner, repo, "preview", key).parent
        / f".{key}.state.json"
    )


def _read_preview_state_unlocked(
    owner: str,
    repo: str,
    key: str,
) -> dict | None:
    path = _preview_state_path(owner, repo, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        run_number = _manifest_integer(
            payload.get("run_number"),
            "run_number",
        )
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        raise PreviewArtifactError(
            "Pull-request preview state is invalid."
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != 1
        or payload.get("owner") != owner
        or payload.get("repo") != repo
        or payload.get("environment") != "preview"
        or payload.get("key") != key
        or payload.get("state") not in {"open", "closed", "deleted"}
        or run_number <= 0
    ):
        raise PreviewArtifactError(
            "Pull-request preview state is invalid."
        )
    return {**payload, "run_number": run_number}


def _write_preview_state_unlocked(
    owner: str,
    repo: str,
    key: str,
    *,
    state: str,
    run_number: int,
    source_sha: str | None = None,
) -> dict:
    path = _preview_state_path(owner, repo, key)
    payload = {
        "schema": 1,
        "owner": owner,
        "repo": repo,
        "environment": "preview",
        "key": key,
        "state": state,
        "run_number": run_number,
        "source_sha": source_sha,
        "updated_at": int(time.time()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return payload


def _read_deployment_metadata_unlocked(target: Path) -> dict | None:
    try:
        payload = json.loads(
            (target / ".nyankoface-deployment.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def mark_preview_closed(
    owner: str,
    repo: str,
    key: str,
    *,
    run_number: int,
) -> dict:
    """Persist a monotonic close watermark before removing a PR Preview."""
    target = deployment_path(owner, repo, "preview", key)
    with _publish_lock:
        state = _read_preview_state_unlocked(owner, repo, key)
        deployed = _read_deployment_metadata_unlocked(target)
        watermark = max(
            int((state or {}).get("run_number") or 0),
            int((deployed or {}).get("run_number") or 0),
        )
        if run_number < watermark:
            return {
                "advanced": False,
                "removed": False,
                "run_number": watermark,
                "state": (state or {}).get("state") or "open",
            }
        advanced = not (
            state
            and state.get("state") == "closed"
            and int(state.get("run_number") or 0) == run_number
        )
        if advanced:
            state = _write_preview_state_unlocked(
                owner,
                repo,
                key,
                state="closed",
                run_number=run_number,
            )
        removed = False
        deployed_run = int((deployed or {}).get("run_number") or 0)
        if target.exists() and deployed_run <= run_number:
            shutil.rmtree(target)
            removed = True
        return {
            **(state or {}),
            "advanced": advanced,
            "removed": removed,
        }


def mark_preview_deleted(
    owner: str,
    repo: str,
    key: str,
    *,
    run_number: int,
    source_sha: str,
) -> dict:
    """Retire a Preview and retain a watermark against older artifacts."""
    target = deployment_path(owner, repo, "preview", key)
    with _publish_lock:
        state = _read_preview_state_unlocked(owner, repo, key)
        deployed = _read_deployment_metadata_unlocked(target)
        watermark = max(
            int((state or {}).get("run_number") or 0),
            int((deployed or {}).get("run_number") or 0),
        )
        if run_number < watermark:
            return {
                **(state or {}),
                "advanced": False,
                "removed": False,
                "run_number": watermark,
            }
        advanced = not (
            state
            and state.get("state") == "deleted"
            and int(state.get("run_number") or 0) == run_number
            and state.get("source_sha") == source_sha
        )
        if advanced:
            state = _write_preview_state_unlocked(
                owner,
                repo,
                key,
                state="deleted",
                run_number=run_number,
                source_sha=source_sha,
            )
        removed = False
        deployed_run = int((deployed or {}).get("run_number") or 0)
        if target.exists() and deployed_run <= run_number:
            shutil.rmtree(target)
            removed = True
        return {
            **(state or {}),
            "advanced": advanced,
            "removed": removed,
        }


def _read_staging_tombstone_unlocked(owner: str, repo: str) -> dict | None:
    path = _staging_tombstone_path(owner, repo)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def mark_staging_deleted(
    owner: str,
    repo: str,
    *,
    run_number: int,
    source_sha: str,
) -> dict:
    """Atomically remove staging and retain a watermark against older runs."""
    target = deployment_path(owner, repo, "staging", "current")
    tombstone_path = _staging_tombstone_path(owner, repo)
    tombstone = {
        "schema": 1,
        "owner": owner,
        "repo": repo,
        "environment": "staging",
        "operation": "delete",
        "run_number": run_number,
        "source_sha": source_sha,
        "deleted_at": int(time.time()),
    }
    with _publish_lock:
        existing = _read_staging_tombstone_unlocked(owner, repo)
        existing_run = int((existing or {}).get("run_number") or 0)
        if existing_run > run_number:
            return {**existing, "removed": False}
        removed = target.is_dir()
        if removed:
            shutil.rmtree(target)
        tombstone_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = tombstone_path.with_name(
            f".{tombstone_path.name}.tmp-{uuid.uuid4().hex}"
        )
        temporary.write_text(
            json.dumps(tombstone, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, tombstone_path)
        return {**tombstone, "removed": removed}


def publish(
    *,
    owner: str,
    repo: str,
    environment: str,
    key: str,
    artifact_zip: bytes,
    expected_repository: str,
    expected_sha: str,
    expected_run_id: int,
    expected_run_number: int,
    artifact_id: int,
) -> dict:
    """Verify and atomically publish one Actions artifact."""
    if len(artifact_zip) > MAX_ARCHIVE_BYTES:
        raise PreviewArtifactError("Artifact ZIP exceeds the configured size limit.")
    try:
        with _open_artifact_zip(artifact_zip) as archive:
            manifest_info = _zip_member(archive, MANIFEST_NAME)
            site_info = _zip_member(archive, ARCHIVE_NAME)
            if manifest_info.file_size > 64 * 1024:
                raise PreviewArtifactError("Artifact manifest is too large.")
            if site_info.file_size > MAX_ARCHIVE_BYTES:
                raise PreviewArtifactError(
                    "Site archive exceeds the configured size limit."
                )
            with archive.open(manifest_info) as stream:
                manifest_bytes = _read_limited(stream, 64 * 1024)
            with archive.open(site_info) as stream:
                site_bytes = _read_limited(stream, MAX_ARCHIVE_BYTES)
    except PreviewArtifactError:
        raise
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        OSError,
    ) as exc:
        raise PreviewArtifactError("Artifact ZIP is invalid.") from exc

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreviewArtifactError("Artifact manifest is invalid JSON.") from exc
    expected = {
        "schema": 1,
        "repository": expected_repository,
        "sha": expected_sha,
        "artifact": ARCHIVE_NAME,
    }
    if (
        any(manifest.get(name) != value for name, value in expected.items())
        or manifest.get("operation") == "delete"
        or (
            manifest.get("environment") is not None
            and manifest.get("environment") != environment
        )
    ):
        raise PreviewArtifactError("Artifact manifest does not match the Forgejo run.")
    if (
        _manifest_integer(manifest.get("run_id"), "run_id") != expected_run_id
        or _manifest_integer(manifest.get("run_number"), "run_number")
        != expected_run_number
    ):
        raise PreviewArtifactError("Artifact manifest does not match the Forgejo run.")
    digest = hashlib.sha256(site_bytes).hexdigest()
    if manifest.get("artifact_sha256") != digest:
        raise PreviewArtifactError("Artifact SHA-256 verification failed.")

    target = deployment_path(owner, repo, environment, key)
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    backup = target.with_name(f".{target.name}.old-{uuid.uuid4().hex}")
    temporary.mkdir(parents=True, exist_ok=False)
    try:
        _extract_site(site_bytes, temporary)
        metadata = {
            "schema": 1,
            "owner": owner,
            "repo": repo,
            "environment": environment,
            "key": key,
            "source_sha": expected_sha,
            "run_id": expected_run_id,
            "run_number": expected_run_number,
            "artifact_id": artifact_id,
            "artifact_sha256": digest,
            "published_at": int(time.time()),
        }
        (temporary / ".nyankoface-deployment.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        with _publish_lock:
            if environment == "staging":
                tombstone = _read_staging_tombstone_unlocked(owner, repo)
                tombstone_run = int(
                    (tombstone or {}).get("run_number") or 0
                )
                if tombstone_run >= expected_run_number:
                    raise PreviewArtifactError(
                        "Staging artifact is older than its deletion marker."
                    )
            if (
                environment == "preview"
                and (
                    _PR_PREVIEW_KEY.fullmatch(key) is not None
                    or _RUN_PREVIEW_KEY.fullmatch(key) is not None
                )
            ):
                state = _read_preview_state_unlocked(owner, repo, key)
                deployed = _read_deployment_metadata_unlocked(target)
                watermark = max(
                    int((state or {}).get("run_number") or 0),
                    int((deployed or {}).get("run_number") or 0),
                )
                if (
                    expected_run_number < watermark
                    or (
                        state
                        and state.get("state") in {"closed", "deleted"}
                        and expected_run_number
                        <= int(state.get("run_number") or 0)
                    )
                ):
                    raise PreviewArtifactError(
                        "Pull-request Preview artifact is older than its state watermark."
                    )
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                os.replace(target, backup)
            os.replace(temporary, target)
            if backup.exists():
                shutil.rmtree(backup)
            if environment == "staging":
                _staging_tombstone_path(owner, repo).unlink(
                    missing_ok=True
                )
            if (
                environment == "preview"
                and (
                    _PR_PREVIEW_KEY.fullmatch(key) is not None
                    or _RUN_PREVIEW_KEY.fullmatch(key) is not None
                )
            ):
                _write_preview_state_unlocked(
                    owner,
                    repo,
                    key,
                    state="open",
                    run_number=expected_run_number,
                    source_sha=expected_sha,
                )
        return metadata
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise


def metadata(
    owner: str,
    repo: str,
    environment: str,
    key: str,
) -> dict | None:
    target = deployment_path(owner, repo, environment, key)
    with _publish_lock:
        payload = _read_deployment_metadata_unlocked(target)
        if (
            environment == "preview"
            and (
                _PR_PREVIEW_KEY.fullmatch(key) is not None
                or _RUN_PREVIEW_KEY.fullmatch(key) is not None
            )
        ):
            try:
                state = _read_preview_state_unlocked(owner, repo, key)
            except PreviewArtifactError:
                return None
            if (
                state
                and state.get("state") in {"closed", "deleted"}
                and int(state.get("run_number") or 0)
                >= int((payload or {}).get("run_number") or 0)
            ):
                return None
        return payload


def remove(owner: str, repo: str, environment: str, key: str) -> bool:
    target = deployment_path(owner, repo, environment, key)
    with _publish_lock:
        if not target.exists():
            return False
        shutil.rmtree(target)
        return True


def prune_run_previews(
    owner: str,
    repo: str,
    *,
    protected_keys: tuple[str, ...] = (),
    now: float | None = None,
    retention_seconds: int | None = None,
    max_count: int | None = None,
) -> list[str]:
    """Delete expired manual ``run-N`` previews under a bounded policy.

    Repository/PR previews and unknown or malformed directories fail closed:
    only a directory whose metadata exactly matches its run key is eligible.
    """
    preview_root = deployment_path(
        owner,
        repo,
        "preview",
        "run-1",
    ).parent
    if not preview_root.is_dir():
        return []
    current_time = time.time() if now is None else now
    ttl = (
        config.PREVIEW_RUN_RETENTION_SECONDS
        if retention_seconds is None
        else max(0, retention_seconds)
    )
    limit = (
        config.PREVIEW_RUN_MAX_COUNT
        if max_count is None
        else max(1, max_count)
    )
    protected = set(protected_keys)
    candidates: list[tuple[int, float, str, Path]] = []
    with _publish_lock:
        for path in preview_root.iterdir():
            match = _RUN_PREVIEW_KEY.fullmatch(path.name)
            if not match or path.is_symlink() or not path.is_dir():
                continue
            metadata_path = path / ".nyankoface-deployment.json"
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            run_number = int(match.group(1))
            if (
                not isinstance(payload, dict)
                or payload.get("owner") != owner
                or payload.get("repo") != repo
                or payload.get("environment") != "preview"
                or payload.get("key") != path.name
                or payload.get("run_number") != run_number
            ):
                continue
            try:
                published_at = float(payload.get("published_at"))
            except (TypeError, ValueError):
                try:
                    published_at = metadata_path.stat().st_mtime
                except OSError:
                    continue
            candidates.append(
                (run_number, published_at, path.name, path)
            )

        candidates.sort(
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
        kept = 0
        removed: list[str] = []
        for _run_number, published_at, key, path in candidates:
            if key in protected:
                continue
            expired = current_time - published_at > ttl
            over_limit = kept >= limit
            if expired or over_limit:
                shutil.rmtree(path)
                removed.append(key)
            else:
                kept += 1
        return removed


def _asset_path_unlocked(
    owner: str,
    repo: str,
    environment: str,
    key: str,
    requested: str,
) -> Path | None:
    target = deployment_path(owner, repo, environment, key)
    relative = _safe_member_path(requested or "index.html")
    if (
        environment == "preview"
        and (
            _PR_PREVIEW_KEY.fullmatch(key) is not None
            or _RUN_PREVIEW_KEY.fullmatch(key) is not None
        )
    ):
        try:
            state = _read_preview_state_unlocked(owner, repo, key)
        except PreviewArtifactError:
            return None
        deployed = _read_deployment_metadata_unlocked(target)
        if (
            state
            and state.get("state") in {"closed", "deleted"}
            and int(state.get("run_number") or 0)
            >= int((deployed or {}).get("run_number") or 0)
        ):
            return None
    candidate = target.joinpath(*relative.parts)
    try:
        candidate.relative_to(target)
    except ValueError:
        return None
    candidates = [candidate]
    if candidate.suffix == "":
        candidates.append(candidate.with_suffix(".html"))
    candidates.append(candidate / "index.html")
    return next(
        (path for path in candidates if path.is_file()),
        None,
    )


def asset_path(
    owner: str,
    repo: str,
    environment: str,
    key: str,
    requested: str,
) -> Path | None:
    with _publish_lock:
        return _asset_path_unlocked(
            owner,
            repo,
            environment,
            key,
            requested,
        )


def open_asset(
    owner: str,
    repo: str,
    environment: str,
    key: str,
    requested: str,
) -> tuple[BinaryIO, Path, os.stat_result] | None:
    """Open and pin one deployment asset while publication is locked."""
    with _publish_lock:
        path = _asset_path_unlocked(
            owner,
            repo,
            environment,
            key,
            requested,
        )
        if path is None:
            return None
        stream = path.open("rb")
        try:
            stat_result = os.fstat(stream.fileno())
        except Exception:
            stream.close()
            raise
        return stream, path, stat_result
