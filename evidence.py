"""Assembles the single-attempt evidence primitive.

A session is a developer-asserted time window (start -> end), not a
commit range. Everything here is either:

  FACT       directly observed or independently reproduced by Helios
  CLAIM      asserted by the task description, a commit message, etc.
  DISCLOSURE an explicit statement of what Helios could NOT see

Nothing here infers whether the task was accomplished. That judgment
is out of scope for this primitive.
"""

import uuid
from datetime import datetime, timezone

from . import baseline


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_evidence(
    session_id: str,
    task: str,
    repo_path: str,
    started_at: str,
    ended_at: str,
    baseline_snapshot,
    final_snapshot,
    checks_before: list,
    checks_after: list,
) -> dict:
    diff = baseline.diff_stat(repo_path, baseline_snapshot.commit)
    tracked_changed = baseline.changed_files(repo_path, baseline_snapshot.commit)
    commits = baseline.commits_since(repo_path, baseline_snapshot.commit)

    new_untracked = baseline.new_untracked_files(
        baseline_snapshot.untracked_files, final_snapshot.untracked_files
    )
    removed_untracked = baseline.removed_untracked_files(
        baseline_snapshot.untracked_files, final_snapshot.untracked_files
    )

    all_changed_paths = (
        {f["path"] for f in tracked_changed} | set(new_untracked) | set(removed_untracked)
    )
    dependency_manifests_touched = sorted(
        p for p in all_changed_paths if p.split("/")[-1] in baseline.KNOWN_DEPENDENCY_MANIFESTS
    )

    return {
        "session_id": session_id,
        "repo_path": repo_path,
        "started_at": started_at,
        "ended_at": ended_at,
        "claims": {
            "task": task,
            "commit_messages": [c["message"] for c in commits],
        },
        "facts": {
            "baseline": baseline_snapshot.to_dict(),
            "final": final_snapshot.to_dict(),
            "diff_stat": diff,
            "tracked_files_changed": tracked_changed,
            "untracked_files_created": new_untracked,
            "untracked_files_removed": removed_untracked,
            "commits": commits,
            "dependency_manifests_touched": dependency_manifests_touched,
            "checks": {
                "before": checks_before,
                "after": checks_after,
            },
            "left_uncommitted": final_snapshot.dirty or bool(final_snapshot.untracked_files),
        },
        "disclosure": [
            "Helios was not present while work happened; only the state at "
            "start and the state at end are known.",
            "Any intermediate iteration -- failed attempts, reverts, "
            "back-and-forth -- is invisible unless it left a distinct trace "
            "in git history within this window (e.g. an intermediate commit).",
            "Check results reflect the repository at the moment Helios ran "
            "them (start and end), not any point in between.",
        ],
    }


def render_report(evidence: dict) -> str:
    lines = []
    f = evidence["facts"]
    c = evidence["claims"]

    lines.append("SESSION")
    lines.append(f"  id: {evidence['session_id']}")
    lines.append(f"  repo: {evidence['repo_path']}")
    lines.append(f"  window: {evidence['started_at']}  ->  {evidence['ended_at']}")
    lines.append("")

    lines.append("CLAIMS (asserted, not independently verified)")
    lines.append(f"  task: {c['task']}")
    if c["commit_messages"]:
        for m in c["commit_messages"]:
            lines.append(f"  commit message: {m}")
    lines.append("")

    lines.append("FACTS")
    ds = f["diff_stat"]
    lines.append(
        f"  {ds['files_changed']} tracked file(s) changed via git "
        f"(+{ds['insertions']}/-{ds['deletions']} lines)"
    )
    if f["tracked_files_changed"]:
        for entry in f["tracked_files_changed"]:
            lines.append(f"    {entry['path']:<40} {entry['status']}")

    if f["untracked_files_created"]:
        lines.append(
            f"  {len(f['untracked_files_created'])} new untracked file(s) "
            f"(not visible to a commit-based diff):"
        )
        for p in f["untracked_files_created"]:
            lines.append(f"    {p:<40} created (untracked)")
    if f["untracked_files_removed"]:
        for p in f["untracked_files_removed"]:
            lines.append(f"    {p:<40} removed (was untracked)")

    if f["commits"]:
        lines.append(f"  {len(f['commits'])} commit(s) made in this window:")
        for commit in f["commits"]:
            lines.append(f"    {commit['sha'][:8]}  {commit['message']}")
    else:
        lines.append("  0 commits made in this window")

    lines.append(
        f"  working tree at end: "
        f"{'dirty / uncommitted changes present' if f['left_uncommitted'] else 'clean'}"
    )

    if f["dependency_manifests_touched"]:
        lines.append(
            f"  dependency manifest(s) touched: "
            f"{', '.join(f['dependency_manifests_touched'])}"
        )
    lines.append("")

    checks = f["checks"]
    if checks["before"] or checks["after"]:
        lines.append("CHECKS (run independently by Helios, not trusted from the agent)")
        before_by_cmd = {ck["cmd"]: ck for ck in checks["before"]}
        after_by_cmd = {ck["cmd"]: ck for ck in checks["after"]}
        for cmd in after_by_cmd:
            b = before_by_cmd.get(cmd)
            a = after_by_cmd[cmd]
            b_status = ("pass" if b["passed"] else "fail") if b else "n/a"
            a_status = "pass" if a["passed"] else "fail"
            lines.append(f"  {cmd}")
            lines.append(f"    before: {b_status}    after: {a_status}")
        lines.append("")

    lines.append("DISCLOSURE (what this record does NOT establish)")
    for d in evidence["disclosure"]:
        lines.append(f"  - {d}")

    return "\n".join(lines)
