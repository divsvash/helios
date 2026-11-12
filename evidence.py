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
    filesystem_changes = baseline.filesystem_changes(
        baseline_snapshot.filesystem_files, final_snapshot.filesystem_files
    )
    commits = baseline.commits_since(repo_path, baseline_snapshot.commit)
    all_changed_paths = {change["path"] for change in filesystem_changes}
    dependency_manifests_touched = sorted(
        p for p in all_changed_paths if p.split("/")[-1] in baseline.KNOWN_DEPENDENCY_MANIFESTS
    )

    graph = build_evidence_graph(
        session_id=session_id,
        filesystem_changes=filesystem_changes,
        commits=commits,
        checks_before=checks_before,
        checks_after=checks_after,
    )

    disclosure = [
        "Helios observed filesystem state at the start and end of this "
        "developer-asserted window. The file changes report is a net "
        "comparison of those observations, not a Git commit diff.",
        "Any intermediate iteration -- failed attempts, reverts, "
        "back-and-forth -- is invisible unless it left a distinct trace "
        "in git history within this window (e.g. an intermediate commit).",
        "Check results reflect the repository at the moment Helios ran "
        "them (start and end), not any point in between.",
    ]
    unobserved = sorted(
        set(baseline_snapshot.filesystem_unobserved_paths)
        | set(final_snapshot.filesystem_unobserved_paths)
    )
    if unobserved:
        disclosure.append(
            "Helios could not read these filesystem paths at one or both "
            f"boundaries, so it cannot make a change claim about them: {', '.join(unobserved)}"
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
            "filesystem_changes": filesystem_changes,
            "git": {
                "commits_observed": commits,
                "baseline": baseline_snapshot.to_dict(),
                "final": final_snapshot.to_dict(),
            },
            "dependency_manifests_touched": dependency_manifests_touched,
            "checks": {
                "before": checks_before,
                "after": checks_after,
            },
            "left_uncommitted": final_snapshot.dirty or bool(final_snapshot.untracked_files),
        },
        "evidence_graph": graph,
        "disclosure": disclosure,
    }


def build_evidence_graph(
    session_id: str,
    filesystem_changes: list,
    commits: list,
    checks_before: list,
    checks_after: list,
) -> dict:
    """Represent directly observed evidence and its provenance.

    The graph intentionally records facts and their sources only. It does not
    rank implementations, infer causality, or claim that an observed file
    change was made by a particular agent.
    """
    start_state_id = f"state:{session_id}:start"
    end_state_id = f"state:{session_id}:end"
    nodes = [
        {"id": f"attempt:{session_id}", "type": "attempt", "provenance": "developer assertion"},
        {"id": start_state_id, "type": "repository_state", "provenance": "Helios filesystem and Git observation at start"},
        {"id": end_state_id, "type": "repository_state", "provenance": "Helios filesystem and Git observation at end"},
    ]
    edges = [
        {"from": f"attempt:{session_id}", "to": start_state_id, "type": "starts_from", "provenance": "developer-bounded window"},
        {"from": f"attempt:{session_id}", "to": end_state_id, "type": "ends_at", "provenance": "developer-bounded window"},
    ]

    for index, change in enumerate(filesystem_changes):
        node_id = f"file-change:{index}"
        nodes.append({
            "id": node_id,
            "type": "file_change",
            "path": change["path"],
            "status": change["status"],
            "provenance": "Helios filesystem comparison",
        })
        edges.append({"from": f"attempt:{session_id}", "to": node_id, "type": "observed_change", "provenance": "Helios filesystem comparison"})
        edges.append({"from": start_state_id, "to": node_id, "type": "before_state", "provenance": "Helios filesystem observation"})
        edges.append({"from": node_id, "to": end_state_id, "type": "after_state", "provenance": "Helios filesystem observation"})

    for commit in commits:
        node_id = f"commit:{commit['sha']}"
        nodes.append({"id": node_id, "type": "git_commit", "sha": commit["sha"], "provenance": "Git history"})
        edges.append({"from": f"attempt:{session_id}", "to": node_id, "type": "observed_commit", "provenance": "Git history since starting HEAD"})

    for phase, checks in (("before", checks_before), ("after", checks_after)):
        for index, check in enumerate(checks):
            node_id = f"check:{phase}:{index}"
            nodes.append({"id": node_id, "type": "check_run", "phase": phase, "passed": check["passed"], "provenance": "Helios command execution"})
            edges.append({"from": f"attempt:{session_id}", "to": node_id, "type": "independently_verified_by", "provenance": "Helios command execution"})

    return {"nodes": nodes, "edges": edges}


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
    changes = f["filesystem_changes"]
    lines.append(
        f"  {len(changes)} file(s) changed between Helios's start and end "
        "filesystem observations"
    )
    for change in changes:
        lines.append(f"    {change['path']:<40} {change['status']}")

    commits = f["git"]["commits_observed"]
    if commits:
        lines.append(f"  {len(commits)} Git commit(s) observed after starting HEAD:")
        for commit in commits:
            lines.append(f"    {commit['sha'][:8]}  {commit['message']}")
    else:
        lines.append("  0 Git commits observed after starting HEAD")

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

    graph = evidence["evidence_graph"]
    lines.append("")
    lines.append("EVIDENCE GRAPH")
    lines.append(f"  {len(graph['nodes'])} typed evidence node(s), {len(graph['edges'])} provenance edge(s)")

    return "\n".join(lines)
