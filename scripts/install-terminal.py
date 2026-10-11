#!/usr/bin/env python3
"""Build pinned QMLTermWidget into Handler's repo-local QML import path."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


REVISION = "8913504fa2ebd220ebe7c680c32954e1b3c035c5"
REPOSITORY = "https://github.com/Swordfish90/qmltermwidget.git"
PROJECT = Path(__file__).resolve().parents[1]
CACHE_SOURCE = Path.home() / ".cache/handler/qmltermwidget-src"
BUILD_DIR = PROJECT / ".runtime/build/qmltermwidget"
IMPORT_DIR = PROJECT / ".runtime/qml/QMLTermWidget"


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def source_tree() -> Path:
    source = Path(os.environ.get("QMLTERMWIDGET_SOURCE", CACHE_SOURCE))
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", REPOSITORY, str(source))
        run("git", "-C", str(source), "checkout", "--detach", REVISION)
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != REVISION:
        raise SystemExit(
            f"QMLTermWidget source at {source} is {actual}, expected {REVISION}; "
            "check out the pinned revision before building."
        )
    return source


def main() -> None:
    source = source_tree()
    qmake = shutil.which("qmake6") or shutil.which("qmake")
    if not qmake:
        raise SystemExit("qmake6 is required to build the Qt 6 QMLTermWidget plugin")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    run(qmake, str(source / "qmltermwidget.pro"), cwd=BUILD_DIR)
    run("make", "-j", str(min(os.cpu_count() or 2, 4)), cwd=BUILD_DIR)

    built_module = BUILD_DIR / "QMLTermWidget"
    plugin_candidates = list(built_module.glob("*qmltermwidget*.so"))
    if not plugin_candidates:
        raise SystemExit(f"qmake build did not produce a plugin under {built_module}")

    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    for candidate in plugin_candidates:
        shutil.copy2(candidate, IMPORT_DIR / candidate.name)
    for name in ("qmldir", "QMLTermScrollbar.qml"):
        shutil.copy2(source / "src" / name, IMPORT_DIR / name)
    for name in ("LICENSE", "LICENSE.BSD-3-clause", "LICENSE.LGPL2+", "AUTHORS"):
        shutil.copy2(source / name, IMPORT_DIR / name)
    for name in ("color-schemes", "kb-layouts"):
        target = IMPORT_DIR / name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source / "lib" / name, target)
    install_handler_schemes(IMPORT_DIR / "color-schemes")

    print(f"Installed QMLTermWidget {REVISION} into {IMPORT_DIR}")
    print("Handler's launcher adds this repo-local module to QML_IMPORT_PATH for terminal themes and keys.")


def install_handler_schemes(directory: Path) -> None:
    """Write Corso terminal palettes, independent of Handler's interface theme."""
    for name, description, background, foreground, values in (
        (
            "HandlerDark",
            "Corso Dark",
            (19, 21, 25),
            (232, 225, 214),
            ((56, 62, 72), (225, 124, 121), (166, 183, 205), (223, 180, 116),
             (139, 173, 211), (186, 158, 205), (133, 190, 205), (232, 225, 214)),
        ),
        (
            "HandlerLight",
            "Corso Light",
            (245, 242, 235),
            (42, 45, 52),
            ((51, 59, 72), (157, 56, 57), (62, 81, 112), (137, 90, 34),
             (51, 94, 150), (112, 66, 138), (36, 99, 121), (88, 86, 81)),
        ),
    ):
        lines = [
            f"[Background]\nColor={background[0]},{background[1]},{background[2]}",
            f"[BackgroundIntense]\nColor={background[0]},{background[1]},{background[2]}",
            f"[BackgroundFaint]\nColor={background[0]},{background[1]},{background[2]}",
        ]
        direction = 1 if name == "HandlerDark" else -1
        for index, value in enumerate(values):
            for suffix, offset in (("", 0), ("Intense", 18 * direction), ("Faint", -18 * direction)):
                rgb = ",".join(str(max(0, min(255, channel + offset))) for channel in value)
                lines.append(f"[Color{index}{suffix}]\nColor={rgb}")
        for suffix, offset in (("", 0), ("Intense", 16 * direction), ("Faint", -16 * direction)):
            rgb = ",".join(str(max(0, min(255, channel + offset))) for channel in foreground)
            lines.append(f"[Foreground{suffix}]\nColor={rgb}")
        lines.extend(
            (
                "[General]",
                f"Description={description}",
                "Opacity=1",
            )
        )
        (directory / f"{name}.colorscheme").write_text("\n\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
