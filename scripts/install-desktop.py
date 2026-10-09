#!/usr/bin/env python3
"""Install user-level launchers and file association; no root or desktop resets."""
from pathlib import Path
import shlex
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
home = Path.home()
launcher = home / ".local/bin/dog-walker-gui"
launcher.parent.mkdir(parents=True, exist_ok=True)
launcher.write_text("#!/usr/bin/env bash\nset -euo pipefail\nexec bash " + shlex.quote(str(root / "scripts/launch-desktop.sh")) + ' "$@"\n')
launcher.chmod(0o755)
icon = home / ".local/share/icons/hicolor/scalable/apps/dog-walker.svg"
icon.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(root / "native/icon.svg", icon)
desktop = home / ".local/share/applications/dev.dogwalker.App.desktop"
desktop.parent.mkdir(parents=True, exist_ok=True)
desktop.write_text(f'''[Desktop Entry]
Type=Application
Name=Dog Walker
GenericName=Offline AI workflow supervisor
Comment=Keep your local model on track, one verified step at a time
Exec="{launcher}" %f
Icon=dog-walker
Terminal=false
Categories=Development;Utility;
Keywords=AI;local;offline;workflow;agent;
MimeType=application/x-dog-walker;
StartupNotify=true
''')
mime = home / ".local/share/mime/packages/dog-walker.xml"
mime.parent.mkdir(parents=True, exist_ok=True)
mime.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-dog-walker">
    <comment>Dog Walker job form</comment>
    <sub-class-of type="text/plain"/>
    <glob pattern="*.dogwalk"/>
  </mime-type>
</mime-info>
''')
for command in (["update-mime-database", str(mime.parent.parent)],
                ["update-desktop-database", str(desktop.parent)],
                ["xdg-mime", "default", desktop.name, "application/x-dog-walker"]):
    if shutil.which(command[0]):
        subprocess.run(command, check=True)
(home / "Documents/Dog Walker/Inbox").mkdir(parents=True, exist_ok=True)
print("Installed Dog Walker in the app launcher. .dogwalk files now open in Dog Walker.")
