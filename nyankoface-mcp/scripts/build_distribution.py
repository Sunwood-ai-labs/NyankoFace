from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EPOCH = int(os.getenv("SOURCE_DATE_EPOCH", "1767225600"))


def source_files() -> list[Path]:
    files = [ROOT / name for name in ("pyproject.toml", "README.md", "LICENSE", "requirements.lock")]
    files.extend(sorted((ROOT / "nyankoface_mcp").glob("*.py")))
    files.extend(sorted((ROOT / "tests").glob("test_*.py")))
    return files


def add_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mtime = EPOCH
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    archive.addfile(info, __import__("io").BytesIO(content))


def build(out_dir: Path) -> tuple[Path, Path]:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = metadata["version"]
    normalized = metadata["name"].replace("-", "_")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nyankoface-mcp-build-") as temporary:
        clean_root = Path(temporary) / "source"
        for source in source_files():
            target = clean_root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        env = os.environ.copy()
        env.update({"SOURCE_DATE_EPOCH": str(EPOCH), "PYTHONHASHSEED": "0"})
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(out_dir)],
            cwd=clean_root,
            env=env,
            check=True,
        )

    wheel = out_dir / f"{normalized}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as package:
        pkg_info = package.read(f"{normalized}-{version}.dist-info/METADATA")

    sdist = out_dir / f"{normalized}-{version}.tar.gz"
    prefix = f"{normalized}-{version}"
    with sdist.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=EPOCH) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                entries = [(source.relative_to(ROOT).as_posix(), source.read_bytes()) for source in source_files()]
                entries.append(("PKG-INFO", pkg_info))
                for relative, content in sorted(entries):
                    add_bytes(archive, f"{prefix}/{relative}", content)
    return wheel, sdist


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic NyankoFace MCP wheel and sdist")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    for artifact in build(args.out_dir.resolve()):
        print(artifact.name)


if __name__ == "__main__":
    main()
