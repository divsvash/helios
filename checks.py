"""Objective checks Helios runs itself, rather than trusting the
agent's own report of having run them.

Only exit code and duration are treated as facts here. Parsing
framework-specific output ("42 passing") is deliberately out of scope
for this milestone -- exit code is the one signal that generalizes
across test/build/lint tools without per-framework parsers.
"""

import subprocess
import time


def run_checks(repo_path: str, check_cmds: list) -> list:
    results = []
    for cmd in check_cmds:
        start = time.time()
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        end = time.time()
        results.append(
            {
                "cmd": cmd,
                "exit_code": proc.returncode,
                "passed": proc.returncode == 0,
                "duration_s": round(end - start, 3),
                "stdout_tail": "\n".join(proc.stdout.splitlines()[-15:]),
                "stderr_tail": "\n".join(proc.stderr.splitlines()[-15:]),
            }
        )
    return results
