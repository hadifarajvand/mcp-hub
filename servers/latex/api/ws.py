"""Per-subject project workspaces on disk, with strict containment and quotas.

Layout: <ROOT>/<subject>/<project>/<files...>; compile output lives in <dir-of-main>/_build/.
No symlinks are ever created, and any found are rejected. All paths coming from clients go through
`Workspace.resolve`, which refuses absolute paths, `..`, NUL/backslash, hidden names and reserved dirs.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import stat
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(os.getenv("LATEX_DATA_DIR", "/data/ws"))
MAX_PROJECTS = int(os.getenv("LATEX_MAX_PROJECTS", "50"))
MAX_FILES = int(os.getenv("LATEX_MAX_FILES", "500"))
MAX_PROJECT_BYTES = int(os.getenv("LATEX_MAX_PROJECT_MB", "50")) * 1024 * 1024
MAX_SUBJECT_BYTES = int(os.getenv("LATEX_MAX_TOTAL_MB", "500")) * 1024 * 1024
MAX_FILE_BYTES = int(os.getenv("LATEX_MAX_FILE_MB", "10")) * 1024 * 1024
BUILD_DIR = "_build"

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
PART_RE = re.compile(r"^[A-Za-z0-9_@+=,][A-Za-z0-9_@+=,.\- ]{0,99}$")
# Inert data and TeX inputs only. No scripts or binaries (.lua, .pl, .sh, .py, .so, ...).
TEXT_EXT = {"tex", "sty", "cls", "bib", "bst", "bbx", "cbx", "def", "cfg", "clo", "fd", "ldf", "lbx", "dtx", "ins",
            "txt", "md", "csv", "tsv", "json", "yaml", "yml", "dat", "tikz", "pgf", "svg", "eps", "bbl"}
BINARY_EXT = {"png", "jpg", "jpeg", "gif", "pdf", "ttf", "otf"}
ALLOWED_EXT = TEXT_EXT | BINARY_EXT


class WorkspaceError(Exception):
    """Message is safe to show to the client."""


def clean_subject(subject: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", subject or "owner")[:64].lstrip(".") or "owner"
    return s


class Workspace:
    def __init__(self, subject: str, root: Path | None = None):
        self.root = (root or ROOT) / clean_subject(subject)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- names and paths ----
    def project_dir(self, name: str, *, must_exist: bool = True) -> Path:
        if not isinstance(name, str) or not NAME_RE.match(name) or name in (".", ".."):
            raise WorkspaceError("invalid project name (letters, digits, _ . - ; max 64)")
        p = self.root / name
        if must_exist and not p.is_dir():
            raise WorkspaceError(f"project not found: {name}")
        if p.is_symlink():
            raise WorkspaceError("invalid project")
        return p

    @staticmethod
    def check_rel(rel: str, *, allow_empty: bool = False, writing: bool = False, ext_check: bool = False) -> str:
        if not isinstance(rel, str) or "\x00" in rel or "\\" in rel:
            raise WorkspaceError("invalid path")
        rel = rel.strip("/") if rel != "/" else ""
        if not rel:
            if allow_empty:
                return ""
            raise WorkspaceError("path is required")
        parts = rel.split("/")
        for part in parts:
            if part in (".", "..", "") or part.startswith("-") or not PART_RE.match(part):
                raise WorkspaceError("invalid path component (no '..', hidden, or special characters)")
        if writing and parts[0] == BUILD_DIR:
            raise WorkspaceError(f"{BUILD_DIR}/ is reserved for build output")
        if ext_check:
            ext = parts[-1].rsplit(".", 1)[-1].lower() if "." in parts[-1] else ""
            if ext not in ALLOWED_EXT:
                raise WorkspaceError(f"file type not allowed: .{ext or '(none)'} (allowed: {', '.join(sorted(ALLOWED_EXT))})")
        return rel

    def resolve(self, project: str, rel: str, *, allow_empty: bool = False, writing: bool = False, ext_check: bool = False) -> Path:
        base = self.project_dir(project)
        rel = self.check_rel(rel, allow_empty=allow_empty, writing=writing, ext_check=ext_check)
        target = base / rel if rel else base
        # Refuse symlinks anywhere along the way, and re-verify containment after resolution.
        cur = base
        for part in rel.split("/") if rel else []:
            cur = cur / part
            if cur.is_symlink():
                raise WorkspaceError("symlinks are not allowed")
        real_base = base.resolve()
        if target.resolve() != real_base and real_base not in target.resolve().parents:
            raise WorkspaceError("path escapes the project")
        return target

    # ---- projects ----
    def list_projects(self) -> list[dict]:
        out = []
        for p in sorted(self.root.iterdir()):
            if p.is_dir() and not p.is_symlink() and NAME_RE.match(p.name):
                files, size = self.usage(p)
                out.append({"name": p.name, "files": files, "bytes": size, "modified": int(p.stat().st_mtime)})
        return out

    def create_project(self, name: str, files: dict[str, bytes]) -> Path:
        p = self.project_dir(name, must_exist=False)
        if p.exists():
            raise WorkspaceError(f"project already exists: {name}")
        if len(self.list_projects()) >= MAX_PROJECTS:
            raise WorkspaceError(f"project limit reached ({MAX_PROJECTS})")
        p.mkdir()
        try:
            for rel, data in files.items():
                self.write(name, rel, data)
        except Exception:
            shutil.rmtree(p, ignore_errors=True)
            raise
        return p

    def delete_project(self, name: str) -> None:
        shutil.rmtree(self.project_dir(name))

    # ---- usage / quotas ----
    @staticmethod
    def usage(p: Path, skip_build: bool = False) -> tuple[int, int]:
        files = size = 0
        for f in p.rglob("*"):
            if f.is_file() and not f.is_symlink():
                if skip_build and f.relative_to(p).parts[0] == BUILD_DIR:
                    continue
                files += 1
                size += f.stat().st_size
        return files, size

    def subject_bytes(self) -> int:
        return sum(self.usage(p)[1] for p in self.root.iterdir() if p.is_dir() and not p.is_symlink())

    def _check_quota(self, project: str, extra_files: int, extra_bytes: int) -> None:
        files, size = self.usage(self.project_dir(project))
        if files + extra_files > MAX_FILES:
            raise WorkspaceError(f"project file limit reached ({MAX_FILES})")
        if size + extra_bytes > MAX_PROJECT_BYTES:
            raise WorkspaceError(f"project size limit reached ({MAX_PROJECT_BYTES // 1024 // 1024} MB)")
        if self.subject_bytes() + extra_bytes > MAX_SUBJECT_BYTES:
            raise WorkspaceError(f"workspace size limit reached ({MAX_SUBJECT_BYTES // 1024 // 1024} MB)")

    # ---- file operations ----
    def write(self, project: str, rel: str, data: bytes, *, overwrite: bool = True) -> Path:
        if len(data) > MAX_FILE_BYTES:
            raise WorkspaceError(f"file too large (max {MAX_FILE_BYTES // 1024 // 1024} MB)")
        target = self.resolve(project, rel, writing=True, ext_check=True)
        exists = target.exists()
        if exists and not overwrite:
            raise WorkspaceError(f"file exists: {rel}")
        if exists and not target.is_file():
            raise WorkspaceError(f"not a file: {rel}")
        old = target.stat().st_size if exists else 0
        self._check_quota(project, 0 if exists else 1, max(0, len(data) - old))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        return target

    def read(self, project: str, rel: str) -> bytes:
        target = self.resolve(project, rel)
        if not target.is_file():
            raise WorkspaceError(f"file not found: {rel}")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError("file too large to read")
        return target.read_bytes()

    def delete(self, project: str, rel: str) -> None:
        target = self.resolve(project, rel, writing=True)
        if not target.is_file():
            raise WorkspaceError(f"file not found: {rel}")
        target.unlink()

    def move(self, project: str, src: str, dst: str, *, overwrite: bool = False) -> None:
        s = self.resolve(project, src, writing=True)
        d = self.resolve(project, dst, writing=True, ext_check=True)
        if not s.is_file():
            raise WorkspaceError(f"file not found: {src}")
        if d.exists() and not overwrite:
            raise WorkspaceError(f"destination exists: {dst}")
        d.parent.mkdir(parents=True, exist_ok=True)
        os.replace(s, d)

    def list_files(self, project: str, rel: str = "", include_build: bool = False) -> list[dict]:
        base = self.project_dir(project)
        start = self.resolve(project, rel, allow_empty=True)
        out = []
        for f in sorted(start.rglob("*")):
            if f.is_symlink() or not f.is_file():
                continue
            r = f.relative_to(base).as_posix()
            if r.startswith(BUILD_DIR + "/") and not include_build:
                continue
            st = f.stat()
            out.append({"path": r, "bytes": st.st_size, "modified": int(st.st_mtime)})
            if len(out) >= 2000:
                break
        return out

    # ---- archives ----
    def tar_for_worker(self, project: str, only: list[str] | None = None) -> bytes:
        """tar.gz of the project (without build output) for the sandbox worker."""
        base = self.project_dir(project)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=3) as tf:
            for f in sorted(base.rglob("*")):
                rel = f.relative_to(base)
                if f.is_symlink() or not f.is_file() or rel.parts[0] == BUILD_DIR or rel.parts[0].startswith("."):
                    continue
                if only is not None and rel.as_posix() not in only:
                    continue
                info = tf.gettarinfo(str(f), arcname=rel.as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with f.open("rb") as fh:
                    tf.addfile(info, fh)
        return buf.getvalue()

    @staticmethod
    def tar_of(files: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=3) as tf:
            for rel, data in files.items():
                info = tarfile.TarInfo(rel)
                info.size, info.mode = len(data), 0o644
                tf.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    def zip_project(self, project: str, include_build: bool = False) -> bytes:
        base = self.project_dir(project)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(base.rglob("*")):
                rel = f.relative_to(base).as_posix()
                if f.is_symlink() or not f.is_file() or (rel.startswith(BUILD_DIR + "/") and not include_build):
                    continue
                zf.write(f, rel)
        return buf.getvalue()

    def extract_zip(self, project: str, data: bytes, *, replace: bool = False) -> int:
        """Extract an untrusted zip: no symlinks, traversal, odd names, or bombs. Returns file count."""
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise WorkspaceError("not a valid zip archive") from e
        entries = [i for i in zf.infolist() if not i.is_dir()]
        for i in entries:  # judge the RAW name: normalisation below must never "fix" a hostile entry
            if i.filename.startswith("/") or "\\" in i.filename or ".." in i.filename.split("/") or "\x00" in i.filename:
                raise WorkspaceError(f"unsafe path in archive: {i.filename[:80]!r}")
        if len(entries) > MAX_FILES:
            raise WorkspaceError(f"archive has too many files (max {MAX_FILES})")
        # Strip a single top-level directory (common with downloaded projects).
        tops = {i.filename.split("/")[0] for i in entries}
        strip = len(tops) == 1 and all("/" in i.filename for i in entries)
        total = 0
        plan: list[tuple[str, zipfile.ZipInfo]] = []
        for info in entries:
            if stat.S_ISLNK(info.external_attr >> 16):
                raise WorkspaceError("archive contains a symlink")
            name = info.filename.split("/", 1)[1] if strip else info.filename
            rel = self.check_rel(name, writing=True, ext_check=True)
            if info.file_size > MAX_FILE_BYTES:
                raise WorkspaceError(f"file too large in archive: {rel}")
            total += info.file_size
            if total > MAX_PROJECT_BYTES:
                raise WorkspaceError("archive expands beyond the project size limit")
            plan.append((rel, info))
        if replace:
            base = self.project_dir(project)
            for f in list(base.iterdir()):
                shutil.rmtree(f) if f.is_dir() else f.unlink()
        for rel, info in plan:
            with zf.open(info) as src:
                # Read with a hard cap: declared sizes in zip headers can lie.
                data_ = src.read(MAX_FILE_BYTES + 1)
            self.write(project, rel, data_)
        return len(plan)

    def replace_build(self, project: str, build_rel: str, outputs: dict[str, bytes]) -> None:
        """Replace <build_rel>/ with compile outputs from the worker (already filtered by it)."""
        base = self.project_dir(project)
        d = base / build_rel
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
        for name, data in outputs.items():
            p = d / Path(name).name
            p.write_bytes(data)

    def prune(self, max_age_days: int) -> int:
        """Delete projects untouched for `max_age_days`. Returns number deleted."""
        cutoff, n = time.time() - max_age_days * 86400, 0
        for p in self.root.iterdir():
            if p.is_dir() and not p.is_symlink() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                n += 1
        return n
