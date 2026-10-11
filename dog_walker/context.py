"""Bounded, fresh project discovery without inference or a persistent index."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

from .workflow import WalkerError, inside

MAX_FILES = 5000
MAX_BYTES = 20 * 1024 * 1024
MAX_READ = 64 * 1024
MAX_OUTPUT = 15000  # Leave room for the broker envelope.
EXCLUDED = {".git", ".ssh", ".codex", "node_modules", ".venv", "venv", "__pycache__",
            ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", "dist", "build", "target", "coverage", "artifacts"}
MANIFESTS = {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "Makefile", "requirements.txt", "CMakeLists.txt"}
ENTRYPOINTS = {"main.py", "__main__.py", "app.py", "cli.py", "main.rs", "main.go", "index.html", "index.js", "index.ts", "server.js"}
SOURCES = {".py", ".js", ".jsx", ".ts", ".tsx", ".qml", ".rs", ".go", ".c", ".h", ".cpp", ".hpp", ".java", ".swift", ".sh", ".html", ".css", ".sql"}


def excluded(path):
    return any(p in EXCLUDED or p.startswith(".env") or p.endswith(".egg-info") for p in Path(path).parts)


def kind(path):
    p = Path(path)
    if p.name in MANIFESTS:
        return "manifest"
    if any(part in {"tests", "test", "__tests__"} for part in p.parts) or p.name.startswith("test_") or ".test." in p.name or ".spec." in p.name:
        return "test"
    if p.name in ENTRYPOINTS:
        return "entrypoint"
    return "source" if p.suffix in SOURCES else "text"


def read_source(root, relative):
    """Open each component without following links, including concurrent replacements."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in {".", ".."} for p in parts) or excluded(relative):
        raise WalkerError("Choose a supported relative project file")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise OSError("Not a regular project file")
            return stream.read(MAX_READ + 1)
    finally:
        os.close(directory)


class Scan:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise WalkerError("The selected project is unavailable")
        self.files = []
        self.reasons = set()
        self.bytes = 0
        self.visited = 0
        self.started = time.monotonic()
        self.git = shutil.which("git") if (self.root / ".git").exists() else None
        if (self.root / ".git").exists() and not self.git:
            raise WalkerError("Git is needed to respect this project's ignore rules")

    def ignored(self, paths):
        if not self.git or not paths:
            return set()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        result = subprocess.run([self.git, "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                                 "check-ignore", "--no-index", "-z", "--stdin"],
                                cwd=self.root, env=env, input=b"\0".join(os.fsencode(p) for p in paths) + b"\0",
                                capture_output=True, timeout=2)
        if result.returncode not in (0, 1):
            raise WalkerError("Could not read project ignore rules")
        return {os.fsdecode(p) for p in result.stdout.split(b"\0") if p}

    def walk(self, folder, depth=0):
        if depth > 40:
            self.reasons.add("directory depth limit")
            return
        if time.monotonic() - self.started > 10:
            self.reasons.add("scan time limit")
            return
        entries = []
        try:
            with os.scandir(folder) as iterator:
                for entry in iterator:
                    self.visited += 1
                    if self.visited > 20000:
                        self.reasons.add("directory entry limit")
                        break
                    relative = str(Path(entry.path).relative_to(self.root))
                    if not excluded(relative) and not entry.is_symlink():
                        entries.append((relative, entry))
        except OSError:
            self.reasons.add("unreadable directory")
            return
        ignored = self.ignored([p for p, _ in entries])
        for relative, entry in sorted(entries):
            if time.monotonic() - self.started > 10:
                self.reasons.add("scan time limit")
                return
            if relative in ignored:
                continue
            if len(self.files) >= MAX_FILES or self.bytes >= MAX_BYTES or self.visited > 20000:
                self.reasons.add("scan size limit")
                return
            path = inside(self.root, relative)
            try:
                if entry.is_dir(follow_symlinks=False):
                    self.walk(path, depth + 1)
                elif entry.is_file(follow_symlinks=False):
                    if len(relative) > 500 or entry.stat(follow_symlinks=False).st_size > MAX_READ:
                        self.reasons.add("unsupported or oversized files")
                        continue
                    body = read_source(self.root, relative)
                    if len(body) > MAX_READ or self.bytes + len(body) > MAX_BYTES:
                        self.reasons.add("scan size limit")
                        continue
                    self.bytes += len(body)
                    if b"\0" in body:
                        continue
                    try:
                        text = body.decode("utf-8")
                    except UnicodeError:
                        continue
                    self.files.append((relative, text, len(body)))
            except OSError:
                self.reasons.add("unreadable or changed files")

    def run(self):
        self.walk(self.root)
        self.files.sort(key=lambda f: f[0])
        return self


def bounded(result, field):
    while len(json.dumps(result, ensure_ascii=False)) > MAX_OUTPUT and result[field]:
        result[field].pop()
        result["truncated"] = True
        if "output limit" not in result["limits"]:
            result["limits"].append("output limit")
    return result


def metadata(scan):
    return {"files_scanned": len(scan.files), "bytes_scanned": scan.bytes,
            "truncated": bool(scan.reasons), "limits": sorted(scan.reasons)}


def project_map(root):
    scan = Scan(root).run()
    # Put navigational landmarks first when the output needs truncating.
    files = sorted(scan.files, key=lambda f: (kind(f[0]) not in {"manifest", "entrypoint", "test"}, f[0]))
    return bounded({**metadata(scan), "files": [{"path": p, "kind": kind(p), "bytes": n} for p, _, n in files]}, "files")


def project_search(root, query):
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise WalkerError("Enter a literal search of 1–1,000 characters")
    scan = Scan(root).run()
    names = [{"path": path, "match": "filename"} for path, _, _ in scan.files if query in path]
    contents = []
    for path, text, _ in scan.files:
        for number, line in enumerate(text.splitlines(), 1):
            offset = line.find(query)
            if offset >= 0:
                start = max(0, offset - 100)
                contents.append({"path": path, "line": number, "match": "content", "excerpt": line[start:start + 300]})
                if len(contents) >= 200:
                    break
        if len(contents) >= 200:
            scan.reasons.add("match limit")
            break
    return bounded({**metadata(scan), "query": query, "matches": names + contents}, "matches")
