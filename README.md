v=# Helios — single-attempt evidence primitive (P0)

Frozen scope: this is only the primitive. No comparison, no LLM
evaluator, no agent launching/integration. Those come later, once
this primitive has produced real evidence records to design against.

## Install
```
pip install psutil   # not actually used by this primitive, kept for future
```
(No hard dependency beyond the Python standard library + `git` on PATH.)

## Usage

A session is a developer-asserted time window, not a commit range.
Work with whatever agent you want, however you want — Helios never
launches or knows about it.

```
python3 -m helios.cli --db ./helios.db start \
  --repo /path/to/repo \
  --task "Fix authentication" \
  --check "npm test"
```

...work with your agent normally, in any tool, commit or don't...

```
python3 -m helios.cli --db ./helios.db end <session_id> \
  --json-out ./evidence.json
```

```
python3 -m helios.cli --db ./helios.db list
python3 -m helios.cli --db ./helios.db show <session_id>
```

## What this proves

- Time-window diffing, not commit-range diffing: fully uncommitted
  work is captured correctly.
- Untracked files (created but never `git add`-ed) are detected
  explicitly — a commit-based `git diff` never shows these at all,
  and git even collapses new untracked directories to a single line
  by default (`git status --porcelain -uall` is required to see the
  individual files; this tripped the first version of this code and
  is fixed in baseline.py).
- Checks are run independently by Helios at both start and end —
  never trusted from the agent's own claim of having run them.
- Every report has an explicit DISCLOSURE section stating what this
  record does *not* establish (no visibility into intermediate
  iteration, no correctness judgment, nothing inferred).

## What's deliberately not here

No comparison across sessions, no scoring, no AI reasoning layer, no
process launching, no agent integration. The evidence record (JSON)
is the artifact those would eventually consume — not designed yet,
on purpose.
