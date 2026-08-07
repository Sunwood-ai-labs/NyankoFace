import json

from sandbox_profile import docker_options_for


def _write_profile(path, **overrides):
    document = {
        "repositories": ["Example/Diagnostics"],
        "share_namespaces": True,
        "metadata_mount": {
            "source": "/private/metadata",
            "target": "/runtime/metadata",
            "read_only": True,
        },
    }
    document.update(overrides)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_missing_profile_is_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKER_RUNTIME_PROFILE_FILE", str(tmp_path / "missing.json"))

    assert docker_options_for("Example", "Diagnostics") == {}


def test_allowed_repository_receives_read_only_runtime_options(monkeypatch, tmp_path):
    profile = tmp_path / "profile.json"
    _write_profile(profile)
    monkeypatch.setenv("WORKER_RUNTIME_PROFILE_FILE", str(profile))

    assert docker_options_for("example", "diagnostics") == {
        "pid_mode": "host",
        "uts_mode": "host",
        "volumes": {
            "/private/metadata": {
                "bind": "/runtime/metadata",
                "mode": "ro",
            }
        },
    }


def test_unlisted_repository_is_denied(monkeypatch, tmp_path):
    profile = tmp_path / "profile.json"
    _write_profile(profile)
    monkeypatch.setenv("WORKER_RUNTIME_PROFILE_FILE", str(profile))

    assert docker_options_for("example", "other-space") == {}


def test_incomplete_or_writable_mount_fails_closed(monkeypatch, tmp_path):
    profile = tmp_path / "profile.json"
    _write_profile(
        profile,
        metadata_mount={
            "source": "relative/path",
            "target": "/runtime/metadata",
            "read_only": False,
        },
    )
    monkeypatch.setenv("WORKER_RUNTIME_PROFILE_FILE", str(profile))

    assert docker_options_for("example", "diagnostics") == {}
