"""Read Omarchy's generated Ghostty colors without changing desktop settings."""
import hashlib
import os
from pathlib import Path
import re
import tempfile
from .storage import APP_ROOT


def sync_omarchy_theme(home=None, import_dir=None):
    home = Path(home) if home else Path.home()
    directory = Path(import_dir) if import_dir else APP_ROOT / ".runtime/qml/QMLTermWidget/color-schemes"
    if not directory.is_dir():
        return {}
    for path in (home / ".local/state/omarchy/current/theme/ghostty.conf",
                 home / ".config/omarchy/current/theme/ghostty.conf"):
        try:
            if path.stat().st_size > 65536:
                continue
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        colors = {}
        for match in re.finditer(r"(?im)^\s*(background|foreground)\s*=\s*#?([0-9a-f]{6})\s*(?:#.*)?$", body):
            colors[match[1].lower()] = match[2].lower()
        palette = {int(m[1]): m[2].lower() for m in re.finditer(
            r"(?im)^\s*palette\s*=\s*(\d{1,2})\s*=\s*#?([0-9a-f]{6})\s*(?:#.*)?$", body)}
        if set(colors) != {"background", "foreground"} or not all(i in palette for i in range(16)):
            continue
        def rgb(value):
            return ",".join(str(int(value[i:i+2], 16)) for i in (0, 2, 4))
        sections = ["[General]\nDescription=Omarchy current terminal\nOpacity=1"]
        for label in ("Background", "Foreground"):
            for suffix in ("", "Intense", "Faint"):
                sections.append(f"[{label}{suffix}]\nColor={rgb(colors[label.lower()])}")
        for index in range(8):
            for suffix, slot in (("", index), ("Intense", index + 8), ("Faint", index)):
                sections.append(f"[Color{index}{suffix}]\nColor={rgb(palette[slot])}")
        content = "\n\n".join(sections) + "\n"
        name = "Omarchy-" + hashlib.sha256(content.encode()).hexdigest()[:16]
        destination = directory / (name + ".colorscheme")
        try:
            if not destination.exists() or destination.read_text() != content:
                with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(content)
                try:
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
        except OSError:
            return {}
        result = {"terminal_scheme": name, "terminal_background": "#" + colors["background"],
                  "terminal_theme": "Omarchy"}
        try:
            config = (home / ".config/ghostty/config").read_text(encoding="utf-8")[:65536]
            font = re.search(r'(?m)^\s*font-family\s*=\s*"?([^"\n]+)"?\s*$', config)
            size = re.search(r"(?m)^\s*font-size\s*=\s*(\d+)\s*$", config)
            if font:
                result["terminal_font"] = font[1].strip()
            if size and 6 <= int(size[1]) <= 24:
                result["terminal_font_size"] = int(size[1])
        except (OSError, UnicodeError):
            pass
        return result
    return {}
