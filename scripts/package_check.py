"""Build and verify ToolWatch wheel/sdist contents and clean-environment startup."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
REQUIRED_ASSETS = (
    "toolwatch/web/templates/base.html",
    "toolwatch/web/static/toolwatch.css",
    "toolwatch/py.typed",
)


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    shutil.rmtree(DIST, ignore_errors=True)
    _run(["uv", "build", "--offline"])
    wheel = next(DIST.glob("toolwatch-0.1.0-*.whl"))
    sdist = next(DIST.glob("toolwatch-0.1.0.tar.gz"))

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for asset in REQUIRED_ASSETS:
            if asset not in names:
                raise RuntimeError(f"wheel missing {asset}")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode()
        if "Version: 0.1.0" not in metadata or "License-Expression: Apache-2.0" not in metadata:
            raise RuntimeError("wheel metadata is incomplete")
    with tarfile.open(sdist) as archive:
        names = set(archive.getnames())
        if not any(name.endswith("/LICENSE") for name in names):
            raise RuntimeError("sdist missing LICENSE")

    with tempfile.TemporaryDirectory(prefix="toolwatch-package-") as directory:
        venv = Path(directory)
        _run(["uv", "venv", "--python", "3.13", str(venv)])
        python = venv / "bin" / "python"
        _run(["uv", "pip", "install", "--python", str(python), str(wheel)])
        _run([str(python), "-c", "import toolwatch; assert toolwatch.__version__ == '0.1.0'"])
        _run([str(python), "-m", "toolwatch.agent", "--help"])
        smoke = """
import asyncio
import httpx
from toolwatch.main import create_app

async def run():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")
        assert response.status_code == 200

asyncio.run(run())
"""
        _run([str(python), "-c", smoke])
    print(f"verified wheel={wheel.name} sdist={sdist.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
