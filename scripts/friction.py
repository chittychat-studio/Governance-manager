"""Friction: how often Governor blocked or asked, per rule, from the hook log (SPEC EV4). Stdlib only (E8).

Usage: python scripts/friction.py <repo> [--days 14]
Counts only; the log never holds commands or file contents (P6, TM1).
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

LOG = ".claude/governor/governor.log"
LINE = re.compile(r"^(\S+)\s+\S+\s+(?:(deny|ask)\s+(\S+)|stop_tests (block) rule=(\S+)|secret_scan ran rule=(\S+) hits=(\d+))")


def counts(repo, days=14, now=None):
    """{rule: {"deny": n, "ask": n}} over the last `days` days. Stop-hook and secret-scan blocks count as deny."""
    p = Path(repo) / LOG
    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(days=days)
    out = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(line)
        if not m:
            continue
        try:
            ts = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
        if ts < since:
            continue
        if m.group(2):
            kind, rule = m.group(2), m.group(3)
        elif m.group(4):
            kind, rule = "deny", m.group(5)
        elif int(m.group(7)) > 0:
            kind, rule = "deny", m.group(6)
        else:
            continue
        out.setdefault(rule, {"deny": 0, "ask": 0})[kind] += 1
    return out


def summary_lines(repo, days=14):
    c = counts(repo, days)
    if not c:
        return [f"Nothing blocked or asked in the last {days} days."]
    lines = [f"Last {days} days: {sum(v['deny'] for v in c.values())} blocked, "
             f"{sum(v['ask'] for v in c.values())} asked you first."]
    for rule, v in sorted(c.items(), key=lambda kv: -(kv[1]["deny"] + kv[1]["ask"])):
        lines.append(f"- {rule}: {v['deny']} blocked, {v['ask']} asked")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args(argv)
    print("\n".join(summary_lines(args.repo, args.days)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
