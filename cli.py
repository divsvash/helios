import argparse
import json
import sys
from pathlib import Path

from . import baseline, checks, evidence, storage

DEFAULT_DB = str(Path.home() / ".helios" / "helios.db")


def cmd_start(args):
    repo_path = str(Path(args.repo).resolve())
    session_id = evidence.new_session_id()
    started_at = evidence.now_iso()

    base_snapshot = baseline.snapshot(repo_path)

    checks_before = []
    if args.check:
        print("[helios] running baseline checks...")
        checks_before = checks.run_checks(repo_path, args.check)
        for c in checks_before:
            print(f"    {c['cmd']}: {'pass' if c['passed'] else 'fail'}")

    conn = storage.get_connection(args.db)
    storage.open_session(
        conn, session_id, repo_path, args.task, started_at, args.check, checks_before, base_snapshot
    )

    print(f"[helios] session started: {session_id}")
    print(f"[helios] baseline commit: {base_snapshot.commit}")
    print(f"[helios] work with your agent normally, then run:")
    print(f"    python3 -m helios.cli --db {args.db} end {session_id}")


def cmd_end(args):
    conn = storage.get_connection(args.db)
    repo_path = str(Path(args.repo).resolve()) if args.repo else None
    session = storage.get_open_session(conn, args.session_id, repo_path)
    if not session:
        print("No matching open session found.", file=sys.stderr)
        sys.exit(1)

    session_id = session["session_id"]
    repo_path = session["repo_path"]
    check_cmds = session["check_cmds"]

    row = conn.execute(
        "SELECT baseline_json, created_at FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    baseline_dict = json.loads(row[0])
    started_at = row[1]
    base_snapshot = baseline.GitSnapshot(
        commit=baseline_dict["commit"],
        branch=baseline_dict["branch"],
        dirty=baseline_dict["dirty"],
        tracked_dirty_files=baseline_dict["tracked_dirty_files"],
        untracked_files=baseline_dict["untracked_files"],
    )
    checks_before = session["checks_before"]

    final_snapshot = baseline.snapshot(repo_path)

    checks_after = []
    if check_cmds:
        print("[helios] running end-of-session checks...")
        checks_after = checks.run_checks(repo_path, check_cmds)
        for c in checks_after:
            print(f"    {c['cmd']}: {'pass' if c['passed'] else 'fail'}")

    ended_at = evidence.now_iso()
    record = evidence.build_evidence(
        session_id=session_id,
        task=session["task"],
        repo_path=repo_path,
        started_at=started_at,
        ended_at=ended_at,
        baseline_snapshot=base_snapshot,
        final_snapshot=final_snapshot,
        checks_before=checks_before,
        checks_after=checks_after,
    )

    storage.close_session(conn, session_id, ended_at, record)

    print()
    print("=" * 60)
    print(evidence.render_report(record))
    print("=" * 60)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(record, indent=2))
        print(f"\n[helios] evidence written to {args.json_out}")


def cmd_list(args):
    conn = storage.get_connection(args.db)
    sessions = storage.list_sessions(conn)
    if not sessions:
        print("No sessions recorded yet.")
        return
    for s in sessions:
        print(
            f"{s['session_id']}  [{s['status']:<6}]  {s['created_at']}  "
            f"{s['task'][:45]}  ({s['repo_path']})"
        )


def cmd_show(args):
    conn = storage.get_connection(args.db)
    record = storage.get_evidence(conn, args.session_id)
    if not record:
        print(
            f"No closed session with evidence found for id {args.session_id}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(evidence.render_report(record))


def main():
    parser = argparse.ArgumentParser(prog="helios")
    parser.add_argument("--db", default=DEFAULT_DB, help="path to local session database")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="capture a baseline and open a session")
    p_start.add_argument("--repo", required=True, help="path to the git repository")
    p_start.add_argument("--task", required=True, help="what the agent is being asked to do")
    p_start.add_argument(
        "--check",
        action="append",
        default=[],
        help="deterministic check command (repeatable), e.g. --check 'npm test'",
    )
    p_start.set_defaults(func=cmd_start)

    p_end = sub.add_parser("end", help="capture final state and close a session")
    p_end.add_argument("session_id", nargs="?", default=None)
    p_end.add_argument("--repo", default=None, help="scope to a repo if session_id is omitted")
    p_end.add_argument("--json-out", default=None, help="write full evidence JSON to this path")
    p_end.set_defaults(func=cmd_end)

    p_list = sub.add_parser("list", help="list sessions")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="print the evidence report for a closed session")
    p_show.add_argument("session_id")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
