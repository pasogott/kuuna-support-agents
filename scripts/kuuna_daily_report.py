#!/usr/bin/env python3
"""
Generate a client-facing daily engineering report for Kuuna from local git facts.

Time methodology (transparent, no IDE extensions):
- Primary signal: committer timestamps on commits landing on the selected calendar day (repo-local TZ offset).
- "Active session" estimate: cluster commits whose committer times are within --gap-minutes.
- Reports both:
  - sum of per-cluster spans (first->last commit in cluster)
  - overall first->last commit span (often wider; useful as an upper bound)

GitHub PR/Issue sections are populated only when `gh` works; otherwise explicitly marked unknown.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable


def run(cmd: list[str], cwd: str) -> str:
    p = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{p.stderr.strip()}")
    return p.stdout.strip()


def git_lines(cmd: list[str], cwd: str) -> list[str]:
    out = run(cmd, cwd=cwd)
    return [ln for ln in out.splitlines() if ln.strip()]


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    committer_dt: dt.datetime  # aware


def day_narrative(commits: list[Commit]) -> tuple[str, list[str], list[str], list[str]]:
    """
    Return (summary, decision_bullets, problem_bullets, fix_bullets) based on commit subjects.
    This is intentionally conservative and avoids claiming UI work unless commit subjects mention it.
    """
    if not commits:
        return (
            "No committer-dated commits were recorded in the selected day window.",
            ["No architecture decisions can be inferred from commits (no commits)."],
            [],
            [],
        )

    subjects = " \n".join(c.subject for c in commits).lower()

    decision_bullets: list[str] = []
    problem_bullets: list[str] = []
    fix_bullets: list[str] = []

    if "inbound" in subjects or "runtime" in subjects or "template build" in subjects:
        decision_bullets.append(
            "**Execution safety:** treat template builds + resolved runtime images as **hard prerequisites** for inbound execution, not best-effort hints."
        )
    if "runtime-agent" in subjects or "docker" in subjects:
        decision_bullets.append(
            "**Execution placement:** perform template build execution in **runtime-agent** using Docker, with infra explicitly enabling the required capabilities."
        )
    if "devtools" in subjects or "daily report" in subjects or "report" in subjects:
        decision_bullets.append(
            "**Operational hygiene:** keep engineering reporting reproducible (git-backed daily report + optional IDE time checkpoints)."
        )

    if "gh" in subjects:
        # unlikely; keep empty unless we detect explicit markers later
        pass

    if any(c.subject.lower().startswith("fix(") for c in commits):
        fix_bullets.append("**Correctness pass:** includes at least one `fix(...)` commit tightening runtime/template resolution behavior.")

    if any(c.subject.lower().startswith("test(") for c in commits):
        fix_bullets.append("**Test reinforcement:** includes `test(...)` commits updating fixtures/contract coverage for the new execution gates.")

    if any(c.subject.lower().startswith("chore(devtools)") for c in commits) or any(
        "daily report" in c.subject.lower() for c in commits
    ):
        fix_bullets.append("**Tooling:** added/iterated internal reporting utilities (non-client product surface).")

    # Summary: prioritize product-facing themes first
    if ("inbound" in subjects or "runtime-agent" in subjects) and ("template" in subjects or "runtime" in subjects):
        summary = (
            "Hardened the **inbound execution path** against unsafe runtime/template states, extended **runtime-agent** to execute template builds via Docker, "
            "and updated **infra** to support the execution model—plus internal reporting/tooling commits."
        )
    else:
        summary = "Shipped the commits listed below; see subjects for the exact scope."

    if not decision_bullets:
        decision_bullets.append("**No strong cross-cutting decisions inferred** beyond what’s stated in individual commit messages.")

    return summary, decision_bullets, problem_bullets, fix_bullets


def parse_git_dt(s: str) -> dt.datetime:
    # git --date=iso-strict yields like 2026-04-23T13:52:15+01:00
    return dt.datetime.fromisoformat(s)


def commits_for_day(*, repo: str, day: dt.date, tz: dt.tzinfo) -> list[Commit]:
    start = dt.datetime.combine(day, dt.time(0, 0, 0), tzinfo=tz)
    end = dt.datetime.combine(day, dt.time(23, 59, 59), tzinfo=tz)
    since = start.isoformat()
    until = end.isoformat()

    # Newest-first from git; we'll reverse to chronological.
    lines = git_lines(
        [
            "git",
            "log",
            f"--since={since}",
            f"--until={until}",
            "--date=iso-strict",
            "--pretty=format:%H%x09%cd%x09%s",
        ],
        cwd=repo,
    )
    commits: list[Commit] = []
    for ln in lines:
        sha, cds, subj = ln.split("\t", 2)
        commits.append(Commit(sha=sha, committer_dt=parse_git_dt(cds), subject=subj))
    commits.sort(key=lambda c: c.committer_dt)
    return commits


def cluster_durations(
    commits: Iterable[Commit],
    gap_minutes: int,
    *,
    min_session_minutes: int,
    min_commit_minutes: int,
) -> tuple[list[float], float]:
    gap = dt.timedelta(minutes=gap_minutes)
    commits = list(commits)
    if not commits:
        return [], 0.0

    clusters: list[list[Commit]] = []
    cur: list[Commit] = [commits[0]]
    for c in commits[1:]:
        if c.committer_dt - cur[-1].committer_dt <= gap:
            cur.append(c)
        else:
            clusters.append(cur)
            cur = [c]
    clusters.append(cur)

    min_session = dt.timedelta(minutes=min_session_minutes)
    min_commit = dt.timedelta(minutes=min_commit_minutes)

    spans_h: list[float] = []
    for cl in clusters:
        raw = cl[-1].committer_dt - cl[0].committer_dt
        if len(cl) <= 1:
            dur = min_commit
        else:
            dur = max(raw, min_session)
        spans_h.append(dur.total_seconds() / 3600.0)

    overall_raw = commits[-1].committer_dt - commits[0].committer_dt
    overall_h = max(overall_raw, min_session if len(commits) > 1 else min_commit).total_seconds() / 3600.0
    return spans_h, overall_h


def current_branch(repo: str) -> str:
    return run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)


def origin_url(repo: str) -> str:
    try:
        return run(["git", "remote", "get-url", "origin"], cwd=repo)
    except RuntimeError:
        return ""


def upstream(repo: str) -> str | None:
    try:
        return run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], cwd=repo)
    except RuntimeError:
        return None


def try_gh_json(cmd: list[str], cwd: str) -> tuple[bool, str]:
    p = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return False, p.stderr.strip()
    return True, p.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.getcwd(), help="Path to kuuna-support-agents repo")
    ap.add_argument(
        "--date",
        default="",
        help="YYYY-MM-DD in the provided --tz (default: today's date in that tz)",
    )
    ap.add_argument(
        "--tz-offset",
        default="+01:00",
        help="Fixed timezone offset for the report day window, e.g. +01:00 (WAT)",
    )
    ap.add_argument("--gap-minutes", type=int, default=120, help="Commit clustering gap for session estimate")
    ap.add_argument(
        "--min-session-minutes",
        type=int,
        default=45,
        help="Minimum credited duration for a multi-commit cluster (captures work between commits)",
    )
    ap.add_argument(
        "--min-commit-minutes",
        type=int,
        default=25,
        help="Minimum credited duration for a single-commit cluster (captures commit-sized work)",
    )
    ap.add_argument(
        "--engineering-hours",
        type=float,
        default=0.0,
        help=(
            "Optional override for client-facing 'engineering hours' for the day. "
            "If set (>0), the report will label it explicitly as a declared override (not git-derived)."
        ),
    )
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"ERROR: not a git repo: {repo}", file=sys.stderr)
        return 2

    # Fixed-offset tz (stable, no zoneinfo dependency), e.g. +01:00
    sign = 1 if args.tz_offset.strip().startswith("+") else -1
    hhmm = args.tz_offset.strip().lstrip("+-")
    hh_s, mm_s = hhmm.split(":", 1)
    delta = dt.timedelta(hours=int(hh_s), minutes=int(mm_s)) * sign
    tz = dt.timezone(delta)

    if args.date:
        day = dt.date.fromisoformat(args.date)
    else:
        day = dt.datetime.now(tz=tz).date()

    commits = commits_for_day(repo=repo, day=day, tz=tz)
    spans_h, overall_h = cluster_durations(
        commits,
        args.gap_minutes,
        min_session_minutes=args.min_session_minutes,
        min_commit_minutes=args.min_commit_minutes,
    )
    active_sum_h = sum(spans_h) if spans_h else 0.0

    summary, decision_bullets, problem_bullets, fix_bullets = day_narrative(commits)

    branch = current_branch(repo)
    origin = origin_url(repo)
    ups = upstream(repo)

    # GitHub activity via gh (best effort)
    pr_lines: list[str] = []
    gh_pr_ok, gh_pr_out = try_gh_json(
        [
            "gh",
            "search",
            "prs",
            "--repo",
            "pasogott/kuuna-support-agents",
            "--limit",
            "20",
            "--json",
            "number,title,state,updatedAt,url",
        ],
        cwd=repo,
    )
    if gh_pr_ok:
        prs = json.loads(gh_pr_out)
        day_s = day.isoformat()
        for pr in prs:
            updated = pr.get("updatedAt", "")
            if isinstance(updated, str) and updated.startswith(day_s):
                pr_lines.append(f"#{pr.get('number')} {pr.get('title')} ({pr.get('state')}) — {pr.get('url')}")
    else:
        pr_lines = [f"Unknown (gh unavailable): {gh_pr_out[:200]}"]

    issue_lines: list[str] = []
    gh_is_ok, gh_is_out = try_gh_json(
        [
            "gh",
            "search",
            "issues",
            "--repo",
            "pasogott/kuuna-support-agents",
            "--limit",
            "20",
            "--json",
            "number,title,state,updatedAt,url",
        ],
        cwd=repo,
    )
    if gh_is_ok:
        issues = json.loads(gh_is_out)
        day_s = day.isoformat()
        for it in issues:
            updated = it.get("updatedAt", "")
            if isinstance(updated, str) and updated.startswith(day_s):
                issue_lines.append(f"#{it.get('number')} {it.get('title')} ({it.get('state')}) — {it.get('url')}")
    else:
        issue_lines = [f"Unknown (gh unavailable): {gh_is_out[:200]}"]

    # Render report (English, client-facing)
    print(f"# Daily Developer Report — {day.isoformat()}")
    print()
    print("## Project: `pasogott/kuuna-support-agents`")
    print("### Summary")
    if not commits:
        print(f"No committer-dated commits found on **{day.isoformat()}** (`{origin}`), branch **`{branch}`**.")
    else:
        print(summary)
    print()
    print("### Work completed")
    if not commits:
        print("- No commits recorded for this day window (committer timestamps).")
    else:
        for c in commits:
            print(f"- `{c.sha[:7]}` — {c.subject}")
    print()
    print("### Decisions / findings")
    for b in decision_bullets:
        print(f"- {b}")
    print()
    print("### Problems encountered")
    print(
        "- **GitHub metadata retrieval:** `gh` may be unavailable/invalid in some environments, which blocks authoritative PR/issue listings."
    )
    if ups is None:
        print("- **Branch tracking:** no configured upstream for the active branch (workflow friction; not necessarily a merge blocker).")
    for b in problem_bullets:
        print(f"- {b}")
    print()
    print("### Fixes or workarounds applied")
    if fix_bullets:
        for b in fix_bullets:
            print(f"- {b}")
    else:
        print("- **None inferred beyond individual commit messages.**")
    print(
        "- **Reporting workaround:** time-on-task is estimated from **git committer clustering** (transparent; see end summary)."
    )
    print()
    print("### GitHub activity")
    print("- **Commits:**")
    if not commits:
        print("  - (none in day window)")
    else:
        for c in commits:
            print(f"  - `{c.sha[:7]}` {c.subject}")
    print("- **Pull Requests:**")
    if pr_lines and pr_lines[0].startswith("Unknown"):
        for ln in pr_lines:
            print(f"  - {ln}")
    else:
        if not pr_lines:
            print("  - None detected for this date via `gh search prs` (or no updates on this date).")
        else:
            for ln in pr_lines:
                print(f"  - {ln}")
    print("- **Issues:**")
    if issue_lines and issue_lines[0].startswith("Unknown"):
        for ln in issue_lines:
            print(f"  - {ln}")
    else:
        if not issue_lines:
            print("  - None detected for this date via `gh search issues` (or no updates on this date).")
        else:
            for ln in issue_lines:
                print(f"  - {ln}")
    print("- **Branches worked on:**")
    print(f"  - `{branch}`")
    print()
    print("### Current status")
    print(f"- Repo: `{repo}`")
    print(f"- Remote: `{origin}`")
    print(f"- Active branch: `{branch}`")
    if commits:
        print(f"- Latest commit in day window: `{commits[-1].sha[:7]}` ({commits[-1].committer_dt.isoformat()})")
    print()
    print("### Next steps")
    print("- If `gh` is failing: restore authentication and regenerate PR/issue sections from GitHub for auditability.")
    print("- Set upstream tracking on the active feature branch to reduce push/pull ambiguity.")
    print("- Run CI/smoke on the integrated template-build path (worker + internal API + dashboard).")
    print()
    print("## Time on task (non-extension method)")
    print(
        f"- **Method:** committer-timestamp clustering within **{args.gap_minutes} minutes** between consecutive commits; "
        f"each cluster credits at least **{args.min_commit_minutes}m** for a single commit, and at least **{args.min_session_minutes}m** "
        "for multi-commit clusters (captures work between rapid commits). Also reports a **first→last commit** span as a cross-check."
    )
    if args.engineering_hours and args.engineering_hours > 0:
        print(f"- **Declared engineering hours (override):** **{args.engineering_hours:.2f} h**")
        print(
            "- **Git-derived estimate (same method, for transparency):** "
            + (
                "**0.00 h** (no commits)"
                if not commits
                else f"**{active_sum_h:.2f} h** (cluster sum), cross-check span **{overall_h:.2f} h**"
            )
        )
        print(
            "- **Note:** the override is **not inferred from git**; use it when your ground truth is calendar/time-tracking "
            "and commits are batched."
        )
    else:
        if not commits:
            print("- **Estimated active engineering time:** **0.0 h** (no commits)")
            print("- **First→last commit span:** **0.0 h**")
        else:
            print(f"- **Clusters:** {len(spans_h)}")
            print(f"- **Sum of cluster spans (estimate):** **{active_sum_h:.2f} h**")
            print(f"- **First→last commit span (upper bound):** **{overall_h:.2f} h**")
            print(
                "- **Caveats:** excludes pure research/planning with no commits; includes bursts where commits are batched; "
                "does not measure uncommitted work."
            )

    print()
    print("## Overall highlights")
    if not commits:
        print("- **Biggest achievement:** no shipped commits in the selected day window (verify timezone/day selection).")
        print("- **Biggest blocker:** unable to demonstrate delivery from git history for the chosen date.")
        print("- **Tomorrow:** confirm the reporting date window and ensure commits land on the intended branch.")
    else:
        if args.engineering_hours and args.engineering_hours > 0:
            print(
                f"- **Engineering time (declared):** **{args.engineering_hours:.2f} h** (override; see Time section for git-derived cross-check)."
            )
        print(
            f"- **Biggest achievement:** landed **{len(commits)}** commits advancing inbound/runtime-agent/template-build execution safety "
            f"(latest: `{commits[-1].sha[:7]}`)."
        )
        if pr_lines and pr_lines[0].startswith("Unknown"):
            print("- **Biggest blocker:** GitHub CLI/API access is failing, so PR/issue sections cannot be audited from the terminal.")
        else:
            print("- **Biggest blocker:** none identified from git metadata alone (review CI + integration risk explicitly).")
        print(
            "- **Tomorrow:** restore `gh` auth (client-auditable PR/issue list), set branch upstream tracking, and run the compose smoke path for worker/API/dashboard integration."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
