"""Builds the Windows installer, Concall-Player-Setup.exe (runs in CI on Windows).

    python packaging/windows/build.py [output-dir]

Collects the app's code, the bundled uv.exe (installs Python and packages on the
user's PC), the launcher and an icon into <output-dir>/build, then compiles
installer.iss with Inno Setup (iscc). Without iscc it stops after collecting,
which is enough to check the layout on any computer.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
UV_VERSION = "0.12.23"  # same as the Mac build


def find_iscc() -> str | None:
    found = shutil.which("iscc")
    if found:
        return found
    for base in (r"C:\Program Files (x86)", r"C:\Program Files"):
        p = Path(base) / "Inno Setup 6" / "ISCC.exe"
        if p.exists():
            return str(p)
    return None


def main(out: Path) -> None:
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "concall" / "__init__.py").read_text(encoding="utf-8")).group(1)
    print(f"Building Concall Player {version} for Windows")
    build = out / "build"
    shutil.rmtree(build, ignore_errors=True)
    (build / "app").mkdir(parents=True)

    # The app's own code (updates later replace this from inside the app).
    shutil.copytree(ROOT / "concall", build / "app" / "concall", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for req in ROOT.glob("requirements*.txt"):
        shutil.copy2(req, build / "app" / req.name)
    shutil.copy2(HERE / "launcher.pyw", build / "launcher.pyw")
    # Batch files need Windows line endings.
    (build / "setup.cmd").write_bytes((HERE / "setup.cmd").read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n").encode())

    # uv.exe: installs Python and packages on first launch and after updates.
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "pip", "download", f"uv=={UV_VERSION}", "--only-binary=:all:",
                        "--platform", "win_amd64", "--no-deps", "-d", tmp, "-q"], check=True)
        wheel = next(Path(tmp).glob("uv-*.whl"))
        with zipfile.ZipFile(wheel) as z:
            name = next(n for n in z.namelist() if n.endswith("/scripts/uv.exe"))
            (build / "uv.exe").write_bytes(z.read(name))

    # Icon: the same drawing as the Mac icon.
    sys.path.insert(0, str(ROOT / "packaging" / "macos"))
    from make_icon import draw

    draw(256).save(build / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    iscc = find_iscc()
    if not iscc:
        print(f"Collected files in {build}; Inno Setup (iscc) not found, so no installer was built.")
        return
    subprocess.run([iscc, f"/DVersion={version}", f"/DBuildDir={build}", str(HERE / "installer.iss")], check=True)
    setup = out / "Concall-Player-Setup.exe"
    print(f"Built: {setup} ({setup.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "dist").resolve())
