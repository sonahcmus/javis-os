"""
git_brain.py - Lớp an toàn dữ liệu cho engine tự học (learn.py / self_improve.py).

Vì sao tồn tại: mọi cơ chế rollback của việc học (snapshot / undo / diff-scope) dựa trên
brain là 1 git repo. NHƯNG mặc định Docker mount `javis-brains:/brains` là named volume
KHÔNG có git (backup git chỉ là bước thủ công comment trong docker-compose). Do đó:

  - Fail-closed: write-mode học CHỈ chạy khi brain là git checkout (is_git_checkout).
    ensure_git_repo() được gọi lúc BẬT học để git-init + commit nền.
  - KHÔNG `git add -A` (tránh commit state bẩn / secret lọt redaction) → chỉ add đúng path
    engine vừa ghi (commit_paths).
  - undo = git revert commit học cuối (revert_last_learn).
  - BrainLock: khoá cấp file (cross-platform) mà MỌI đường ghi (learn worker, curator,
    /reflect, và script backup ngoài nếu hợp tác) phải giành → serialize snapshot→ghi→commit,
    chống đua với tiến trình backup ngoài (asyncio.Lock không bảo vệ được tiến trình khác).

Stdlib-only. Không thêm dependency.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

# Commit ĐÁNG coi là "học" (hiện ở review + undo được). Baseline dùng "chore:" nên KHÔNG
# lọt vào đây → bấm undo khi chưa học gì sẽ báo "không có commit học" thay vì lỡ revert baseline.
# /reflect ghi qua engine nên commit là "learn:" (không phải "reflect:").
LEARN_COMMIT_PREFIXES = ("learn:", "curator:")


def _no_window():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def has_git() -> bool:
    return shutil.which("git") is not None


def _git(root: str, *args, timeout: int = 30) -> subprocess.CompletedProcess:
    """Chạy git trong <root>. KHÔNG raise; caller đọc returncode/stdout."""
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_no_window(),
    )


def is_git_checkout(root: str) -> bool:
    """root có phải git repo (có .git)?"""
    try:
        if not (Path(root) / ".git").exists():
            return False
        r = _git(root, "rev-parse", "--is-inside-work-tree")
        return r.returncode == 0 and "true" in (r.stdout or "").lower()
    except Exception:
        return False


_GITIGNORE = (
    "# Javis brain - KHÔNG commit: khoá, log thô (có thể chứa secret), nhật ký nền.\n"
    "# Git chỉ version TRI THỨC ĐÃ CHƯNG CẤT (facts/wiki/skills/MEMORY.md) → undo sạch, an toàn.\n"
    ".javis-learn.lock\n"
    "Javis/learn-staging/\n"
    "Javis/learn-log/\n"
    "Javis/loop-log/\n"
    "memory/conversations/\n"
    "Memory/conversations/\n"
    "*.tmp\n"
)


def ensure_git_repo(root: str) -> dict:
    """Biến brain thành git repo nếu chưa (gọi khi BẬT học). Idempotent.
    Trả {ok, created, error}. KHÔNG push (backup là việc user chủ động)."""
    root = str(root)
    if not has_git():
        return {"ok": False, "created": False, "error": "Máy chưa cài git"}
    if is_git_checkout(root):
        return {"ok": True, "created": False}
    try:
        Path(root).mkdir(parents=True, exist_ok=True)
        r = _git(root, "init")
        if r.returncode != 0:
            return {"ok": False, "created": False, "error": (r.stderr or "git init lỗi")[:200]}
        # Cấu hình identity cục bộ (repo có thể chạy trong container không có global config)
        _git(root, "config", "user.email", "javis@localhost")
        _git(root, "config", "user.name", "Javis Learn")
        gi = Path(root) / ".gitignore"
        if not gi.exists():
            gi.write_text(_GITIGNORE, encoding="utf-8")
        _git(root, "add", ".gitignore")
        _git(root, "add", "-A")   # commit NỀN duy nhất được phép add -A (baseline, chưa có state học)
        c = _git(root, "commit", "-m", "chore: baseline brain snapshot (bật tự học)")
        return {"ok": True, "created": True, "commit": (c.stdout or "")[:120]}
    except Exception as e:
        return {"ok": False, "created": False, "error": f"{type(e).__name__}: {e}"}


def working_tree_dirty(root: str) -> bool:
    try:
        r = _git(root, "status", "--porcelain")
        return bool((r.stdout or "").strip())
    except Exception:
        return False


def changed_paths(root: str) -> List[str]:
    """Danh sách path đang thay đổi (chưa commit) - dùng cho diff-scope guard."""
    try:
        r = _git(root, "status", "--porcelain")
        out = []
        for line in (r.stdout or "").splitlines():
            # format: 'XY <path>' hoặc 'XY <old> -> <new>'
            p = line[3:].strip() if len(line) > 3 else ""
            if " -> " in p:
                p = p.split(" -> ", 1)[1]
            if p:
                out.append(p.strip('"'))
        return out
    except Exception:
        return []


def paths_within(paths: List[str], allowed_prefixes: List[str]) -> List[str]:
    """Trả path NGOÀI allowed_prefixes (rỗng = hợp lệ). Prefix so theo dạng posix."""
    bad = []
    norm_allowed = [a.replace("\\", "/").rstrip("/") + "/" for a in allowed_prefixes]
    for p in paths:
        pp = p.replace("\\", "/")
        if not any(pp.startswith(a) or (pp + "/").startswith(a) for a in norm_allowed):
            bad.append(p)
    return bad


def commit_paths(root: str, paths: List[str], msg: str) -> Optional[str]:
    """git add ĐÚNG các path (KHÔNG add -A) rồi commit. Trả commit hash ngắn hoặc None.
    An toàn: chỉ đưa vào index những gì engine chủ động ghi."""
    try:
        if not paths:
            return None
        add = _git(root, "add", "--", *paths)
        if add.returncode != 0:
            return None
        c = _git(root, "commit", "-m", msg)
        if c.returncode != 0:
            return None
        h = _git(root, "rev-parse", "--short", "HEAD")
        return (h.stdout or "").strip() or "committed"
    except Exception:
        return None


def hard_reset_paths(root: str, paths: List[str]) -> None:
    """Khôi phục các path về HEAD (dùng khi verify/secret-scan fail sau khi lỡ ghi).
    Chỉ checkout đúng path, không đụng phần còn lại."""
    try:
        if paths:
            _git(root, "checkout", "HEAD", "--", *paths)
            _git(root, "clean", "-fd", "--", *paths)
    except Exception:
        pass


def list_learn_commits(root: str, n: int = 20) -> List[dict]:
    """Liệt kê commit học gần nhất (prefix learn:/curator:/reflect:) + file đổi - cho Review UI."""
    if not is_git_checkout(root):
        return []
    try:
        r = _git(root, "log", "-n", str(n * 3), "--pretty=format:%h\x1f%ct\x1f%s", "--name-only")
        out: List[dict] = []
        blocks = (r.stdout or "").split("\n\n")
        for blk in blocks:
            lines = [l for l in blk.splitlines() if l.strip()]
            if not lines:
                continue
            head = lines[0].split("\x1f")
            if len(head) < 3:
                continue
            h, ct, subj = head[0], head[1], head[2]
            if not any(subj.startswith(p) for p in LEARN_COMMIT_PREFIXES):
                continue
            files = lines[1:]
            out.append({"hash": h, "ts": float(ct or 0), "subject": subj, "files": files})
            if len(out) >= n:
                break
        return out
    except Exception:
        return []


def revert_last_learn(root: str) -> dict:
    """git revert commit HỌC gần nhất (undo 1-click). Trả {ok, reverted, subject, error}."""
    if not is_git_checkout(root):
        return {"ok": False, "error": "Brain chưa phải git repo"}
    try:
        commits = list_learn_commits(root, 1)
        if not commits:
            return {"ok": False, "error": "Không có commit học nào để undo"}
        h = commits[0]["hash"]
        # Chỉ từ chối nếu CHÍNH file trong commit học đó đang bị sửa dở (tránh mất chỉnh tay).
        # File dirty KHÔNG liên quan (conversations/log/note khác) KHÔNG chặn undo.
        target = set(commits[0].get("files") or [])
        overlap = [p for p in changed_paths(root) if p in target]
        if overlap:
            return {"ok": False, "error": f"Các file học đang bị sửa dở, hãy tự xử lý trước: {overlap[:3]}"}
        r = _git(root, "revert", "--no-edit", h)
        if r.returncode != 0:
            _git(root, "revert", "--abort")   # dọn trạng thái revert dở nếu conflict
            return {"ok": False, "error": (r.stderr or "revert lỗi")[:200]}
        return {"ok": True, "reverted": h, "subject": commits[0]["subject"]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ============================================================
# BrainLock - khoá cấp file cross-platform (serialize ghi giữa CÁC tiến trình)
# ============================================================
class BrainLock:
    """Khoá độc quyền theo brain, dựa trên file <root>/.javis-learn.lock.
    POSIX: fcntl.flock; Windows: msvcrt.locking. Non-blocking + retry tới timeout.
    Dùng như context manager (chạy trong worker THREAD, không block event loop)."""

    def __init__(self, root: str, timeout: float = 30.0):
        self.path = Path(root) / ".javis-learn.lock"
        self.timeout = timeout
        self._fh = None
        self._locked = False

    def acquire(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a+")
        except Exception:
            return False
        deadline = time.time() + self.timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._locked = True
                return True
            except OSError:
                if time.time() >= deadline:
                    try:
                        self._fh.close()
                    except Exception:
                        pass
                    self._fh = None
                    return False
                time.sleep(0.25)

    def release(self) -> None:
        if not self._fh:
            return
        try:
            if self._locked:
                if os.name == "nt":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        finally:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
            self._locked = False

    def __enter__(self):
        self.acquired = self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False
