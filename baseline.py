"""Deterministic git-state facts. No inference lives here."""

import subprocess
from dataclasses import dataclass, field
from typing import Optional


def _git(repo_path: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@dataclass
class GitSnapshot:
    commit: Optional[str]
    branch: Optional[str]
    dirty: bool
    tracked_dirty_files: list = field(default_factory=list)
    untracked_files: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "commit": self.commit,
            "branch": self.branch,
            "dirty": self.dirty,
            "tracked_dirty_files": self.tracked_dirty_files,
            "untracked_files": self.untracked_files,
        }


def snapshot(repo_path: str) -> GitSnapshot:
    """Capture the current, verifiable git state of a repository.

    This does not interpret anything. It is a fact-only read of what
    `git` itself already knows.

    Untracked files are separated out deliberately: `git diff` against
    a commit never shows untracked files' content, so a file an agent
    creates but never `git add`s would otherwise be invisible to a
    commit-based diff. Time-window detection needs both lists.
    """
    commit = _git(repo_path, "rev-parse", "HEAD") or None
    branch = _git(repo_path, "branch", "--show-current") or None
    status_lines = [
        line for line in _git(repo_path, "status", "--porcelain", "-uall").splitlines() if line
    ]
    tracked_dirty_files = []
    untracked_files = []
    for line in status_lines:
        code, path = line[:2], line[3:]
        if code.strip() == "??":
            untracked_files.append(path)
        else:
            tracked_dirty_files.append(path)
    return GitSnapshot(
        commit=commit,
        branch=branch,
        dirty=bool(status_lines),
        tracked_dirty_files=tracked_dirty_files,
        untracked_files=untracked_files,
    )


def diff_stat(repo_path: str, baseline_commit: Optional[str]) -> dict:
    """Diff stat between the baseline commit and current working tree.

    Uses the working tree (not just HEAD) so uncommitted changes made
    by an agent that never commits are still counted.
    """
    if baseline_commit is None:
        return {"files_changed": 0, "insertions": 0, "deletions": 0}

    raw = _git(repo_path, "diff", "--numstat", baseline_commit, "--")
    files_changed = 0
    insertions = 0
    deletions = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, _path = parts
        files_changed += 1
        insertions += int(added) if added.isdigit() else 0
        deletions += int(removed) if removed.isdigit() else 0
    return {
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
    }


def changed_files(repo_path: str, baseline_commit: Optional[str]) -> list:
    """Per-file change status (created/modified/deleted) since baseline."""
    if baseline_commit is None:
        return []
    raw = _git(repo_path, "diff", "--name-status", baseline_commit, "--")
    status_map = {"A": "created", "M": "modified", "D": "deleted", "R": "renamed"}
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        code = parts[0][0]
        path = parts[-1]
        out.append({"path": path, "status": status_map.get(code, code)})
    return out


def commits_since(repo_path: str, baseline_commit: Optional[str]) -> list:
    """Commits created after the baseline, if the agent committed anything."""
    if baseline_commit is None:
        return []
    raw = _git(
        repo_path,
        "log",
        f"{baseline_commit}..HEAD",
        "--pretty=format:%H|%an|%aI|%s",
    )
    out = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        sha, author, ts, msg = line.split("|", 3)
        out.append({"sha": sha, "author": author, "timestamp": ts, "message": msg})
    return out


KNOWN_DEPENDENCY_MANIFESTS = {
    "package.json",
    "package-lock.json",
    "requirements.txt",
    "pyproject.toml",
    "Pipfile",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
}


def new_untracked_files(baseline_untracked: list, final_untracked: list) -> list:
    """Untracked files present at the end that weren't present at the
    start -- these are real changes that a commit-based diff would
    never surface, since git diff only ever compares tracked content.
    """
    before = set(baseline_untracked)
    return [p for p in final_untracked if p not in before]


def removed_untracked_files(baseline_untracked: list, final_untracked: list) -> list:
    """Untracked files present at the start that are gone by the end
    (e.g. a scratch file the agent created and then deleted itself,
    still without ever touching git).
    """
    after = set(final_untracked)
    return [p for p in baseline_untracked if p not in after]
