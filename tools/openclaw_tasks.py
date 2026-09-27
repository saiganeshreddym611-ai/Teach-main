#!/usr/bin/env python3
"""Drive OpenClaw, backed by an Ollama model, through TASKS.md one task at a time.

For each eligible task (status `todo`, not a human task, every dependency `done`) the runner:
  1. marks it `in progress` on the TASKS.md status board,
  2. writes a prompt (TASKS.md sections 1-3 + the task section) to .openclaw-runs/<ID>/,
  3. runs `openclaw agent` with that prompt,
  4. runs the test suite (pytest in services/tutor) if the venv exists,
  5. sets the status to `review` (or `done` with --auto-done) or `blocked (...)`,
  6. commits the result if the repo is a git repository.
It stops at the first task that does not finish cleanly.

One-time setup (see `ollama launch openclaw` docs):
    ollama signin
    ollama launch openclaw --model gemma4:31b-cloud --yes

Usage:
    python tools/openclaw_tasks.py status               # board summary + eligible tasks
    python tools/openclaw_tasks.py run --dry-run        # show the next prompt and command only
    python tools/openclaw_tasks.py run                  # run the next eligible task
    python tools/openclaw_tasks.py run --max 5          # run up to 5 tasks in order
    python tools/openclaw_tasks.py run --task T10       # run one specific task
    python tools/openclaw_tasks.py run --max 5 --auto-done   # unattended chaining (skips human review)

Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TASKS_MD = REPO / "TASKS.md"
RUNS_DIR = REPO / ".openclaw-runs"
TUTOR_DIR = REPO / "services" / "tutor"

DEFAULT_MODEL = "ollama/gemma4:31b-cloud"
ROW_RE = re.compile(
    r"^\|\s*(?P<id>T\d{2}|H\d+)\s*\|(?P<title>[^|]*)\|(?P<lane>[^|]*)\|(?P<deps>[^|]*)\|(?P<status>[^|]*)\|\s*$"
)
RESULT_RE = re.compile(r"RESULT:\s*(DONE|BLOCKED)\b[ \t]*([^\n\"\\]*)")


# --------------------------------------------------------------------------- #
# TASKS.md parsing and status updates
# --------------------------------------------------------------------------- #
def read_tasks_md() -> str:
    return TASKS_MD.read_text(encoding="utf-8")


def parse_board(text: str) -> list[dict]:
    board = text.split("## 4. Status board", 1)[-1].split("\n## 5.", 1)[0]
    rows = []
    for line in board.splitlines():
        m = ROW_RE.match(line)
        if not m:
            continue
        deps = [d.strip() for d in m["deps"].split(",") if d.strip() and d.strip() not in {"—", "-"}]
        rows.append({
            "id": m["id"],
            "title": m["title"].strip(),
            "lane": m["lane"].strip(),
            "deps": deps,
            "status": m["status"].strip(),
        })
    if not rows:
        sys.exit("No status board rows found in TASKS.md (section '## 4. Status board').")
    return rows


def eligible(rows: list[dict]) -> list[dict]:
    status = {r["id"]: r["status"] for r in rows}
    return [
        r for r in rows
        if r["status"] == "todo"
        and r["lane"] != "human"
        and all(status.get(d, "").startswith("done") for d in r["deps"])
    ]


def set_status(task_id: str, new_status: str) -> None:
    """Rewrite one status cell. Re-reads the file so edits made by the agent survive."""
    new_status = new_status.replace("|", "/").replace("\n", " ").strip()
    text = read_tasks_md()
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = ROW_RE.match(line.rstrip("\r"))
        if m and m["id"] == task_id:
            cr = "\r" if line.endswith("\r") else ""
            lines[i] = (
                f"| {m['id']} | {m['title'].strip()} | {m['lane'].strip()} | "
                f"{m['deps'].strip()} | {new_status} |{cr}"
            )
            TASKS_MD.write_text("\n".join(lines), encoding="utf-8")
            return
    raise KeyError(f"{task_id} not found on the status board")


def task_section(text: str, task_id: str) -> str:
    m = re.search(rf"^#### {re.escape(task_id)} .*?(?=^#{{2,4}} |\Z)", text, flags=re.M | re.S)
    if not m:
        raise KeyError(f"No '#### {task_id}' section in TASKS.md")
    return m.group(0).strip().removesuffix("---").strip()


def shared_sections(text: str) -> str:
    """Sections 1-3: how to use the file, agent rules, shared contracts."""
    start = text.find("## 1. How to use this file")
    end = text.find("## 4. Status board")
    return text[start:end].strip() if start != -1 and end != -1 else ""


# --------------------------------------------------------------------------- #
# Prompt, agent run, verification
# --------------------------------------------------------------------------- #
PROMPT_TEMPLATE = """You are a coding agent working in the repository at:
{repo}

Use absolute paths under that directory for every file operation. Run every shell command with
that directory (or a subdirectory of it) as the working directory. Do not touch files outside it.

Your task: {id} - {title}

Before you start, read REQUIREMENTS.md and README.md in the repository, then every file the task
lists under "Read first".

Rules for this run:
- Do only this task. Do not start other tasks.
- Do not edit the status board (section 4) in TASKS.md. The runner updates it. You may append rows
  to the Open questions log (section 10).
- Do not push and do not add git remotes. Do not commit, unless the task itself says to make a
  commit (T00). The runner commits your work.
- Run the task's acceptance checks yourself and report their real output. Never claim a check
  passed without running it.
- When you are finished, write one line to the file {result_file}
  and also end your reply with that same line. The line is either the word DONE, or the word
  BLOCKED followed by a one-line reason, prefixed with "RESULT:".

===== TASKS.md sections 1-3 (process, rules, contracts) =====
{shared}

===== Your task =====
{section}
"""


def build_prompt(text: str, row: dict, result_file: Path) -> str:
    return PROMPT_TEMPLATE.format(
        repo=REPO, id=row["id"], title=row["title"], result_file=result_file,
        shared=shared_sections(text), section=task_section(text, row["id"]),
    )


def openclaw_cmd(args, session_id: str, prompt_path: Path) -> list[str]:
    exe = shutil.which("openclaw") or "openclaw"
    cmd = [exe, "agent"]
    if not args.gateway:
        cmd.append("--local")
    cmd += [
        "--session-id", session_id,
        "--message-file", str(prompt_path),
        "--model", args.model,
        "--thinking", args.thinking,
        "--timeout", str(args.timeout),
        "--json",
    ]
    return cmd


def find_result(result_file: Path, stdout: str) -> tuple[str, str]:
    """Return ("DONE"|"BLOCKED"|"UNKNOWN", reason). Prefers the result file the agent writes;
    falls back to the last RESULT line in stdout (the JSON envelope shape can vary between
    OpenClaw versions). Text before the task marker is skipped in case the envelope echoes the
    prompt."""
    if result_file.exists():
        hits = RESULT_RE.findall(result_file.read_text(encoding="utf-8", errors="replace"))
        if hits:
            return hits[-1][0], hits[-1][1].strip()
    marker = stdout.rfind("Your task =====")
    hits = RESULT_RE.findall(stdout[marker:] if marker != -1 else stdout)
    if not hits:
        return "UNKNOWN", "agent reported no RESULT line"
    kind, reason = hits[-1]
    return kind, reason.strip()


def verify(args, log_dir: Path) -> tuple[bool, str]:
    if args.verify:
        cmd, cwd, shell = args.verify, REPO, True
    else:
        py = TUTOR_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not py.exists():
            return True, "skipped (services/tutor/.venv not found)"
        cmd, cwd, shell = [str(py), "-m", "pytest", "-q"], TUTOR_DIR, False
    proc = subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    (log_dir / "verify.txt").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    tail = (proc.stdout.strip().splitlines() or ["(no output)"])[-1]
    return proc.returncode == 0, tail


# --------------------------------------------------------------------------- #
# git helpers (all no-ops when the repo is not a git repository)
# --------------------------------------------------------------------------- #
def is_git() -> bool:
    return (REPO / ".git").exists()


def git(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def dirty() -> bool:
    return bool(git("status", "--porcelain").stdout.strip())


def commit(row: dict, outcome: str, model: str) -> str:
    if not is_git() or not dirty():
        return "nothing to commit"
    git("add", "-A")
    msg = f"{row['id']}: {row['title']}\n\nAutomated run via OpenClaw ({model}). Outcome: {outcome}."
    proc = git("commit", "-m", msg)
    if proc.returncode != 0:
        return f"commit failed: {proc.stderr.strip() or proc.stdout.strip()}"
    return git("rev-parse", "--short", "HEAD").stdout.strip()


def ollama_reachable() -> bool:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    if not host.startswith("http"):
        host = "http://" + host
    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=3):
            return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_status(_args) -> int:
    rows = parse_board(read_tasks_md())
    counts: dict[str, int] = {}
    for r in rows:
        key = r["status"].split(" (")[0]
        counts[key] = counts.get(key, 0) + 1
    print("Board:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for r in rows:
        if r["status"] != "todo":
            print(f"  {r['id']:4} {r['status']}")
    el = eligible(rows)
    print("Eligible now:" if el else "Nothing eligible (check blocked tasks and human tasks).")
    for r in el:
        print(f"  {r['id']:4} {r['title']}")
    return 0


def run_one(args, row: dict) -> bool:
    text = read_tasks_md()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = RUNS_DIR / row["id"] / stamp
    result_file = log_dir / "result.txt"
    prompt = build_prompt(text, row, result_file)
    session_id = f"teach-{row['id']}-{stamp}"

    if args.dry_run:
        log_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = log_dir / "prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        print(f"[dry-run] {row['id']} - {row['title']}")
        print(f"[dry-run] prompt: {prompt_path} ({len(prompt):,} chars)")
        print("[dry-run] command:", subprocess.list2cmdline(openclaw_cmd(args, session_id, prompt_path)))
        return True

    log_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = log_dir / "prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    today = dt.date.today().isoformat()
    set_status(row["id"], f"in progress (openclaw {args.model}, {today})")
    print(f"==> {row['id']} - {row['title']}  (log: {log_dir.relative_to(REPO)})")

    try:
        proc = subprocess.run(
            openclaw_cmd(args, session_id, prompt_path), cwd=REPO, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=args.timeout + 120 if args.timeout else None,
        )
        (log_dir / "stdout.txt").write_text(proc.stdout, encoding="utf-8")
        (log_dir / "stderr.txt").write_text(proc.stderr, encoding="utf-8")
        kind, reason = find_result(result_file, proc.stdout)
        if proc.returncode != 0 and kind != "BLOCKED":
            kind, reason = "BLOCKED", f"openclaw exited {proc.returncode}"
    except subprocess.TimeoutExpired:
        kind, reason = "BLOCKED", "openclaw timed out"
    except KeyboardInterrupt:
        set_status(row["id"], "todo")
        raise
    except Exception as e:  # never leave a task stuck "in progress"
        kind, reason = "BLOCKED", f"runner error: {type(e).__name__}: {e}"

    ok = kind == "DONE"
    if ok:
        passed, tail = verify(args, log_dir)
        print(f"    verify: {'pass' if passed else 'FAIL'} - {tail}")
        if not passed:
            ok, reason = False, f"tests failed after agent reported DONE: {tail}"

    rel = log_dir.relative_to(REPO).as_posix()
    if ok:
        status = f"done (openclaw, {today})" if args.auto_done else f"review (openclaw {args.model}, {today}, log {rel})"
    else:
        status = f"blocked ({reason}; log {rel})"
    set_status(row["id"], status)
    print(f"    status: {status}")

    if ok and not args.no_commit:
        print(f"    commit: {commit(row, 'DONE', args.model)}")
    elif not ok:
        print("    left uncommitted for inspection")
    return ok


def cmd_run(args) -> int:
    if not args.model.count("/"):
        args.model = "ollama/" + args.model
    if not args.dry_run:
        if not shutil.which("openclaw"):
            sys.exit("openclaw not found on PATH. Run: ollama launch openclaw --model gemma4:31b-cloud --yes")
        if "ollama" in args.model and not ollama_reachable():
            print("warning: Ollama is not answering on OLLAMA_HOST / localhost:11434. Start Ollama first.")
        if is_git() and dirty() and not args.allow_dirty:
            sys.exit("Working tree has uncommitted changes. Commit or stash them, or pass --allow-dirty.")

    done_count = 0
    while done_count < args.max:
        rows = parse_board(read_tasks_md())
        if args.task:
            row = next((r for r in rows if r["id"] == args.task), None)
            if row is None:
                sys.exit(f"{args.task} is not on the status board")
            if row["lane"] == "human":
                sys.exit(f"{args.task} is a human task")
        else:
            el = eligible(rows)
            if not el:
                print("Nothing eligible. Run `status` to see what is blocked.")
                break
            row = el[0]
        if not run_one(args, row):
            return 1
        done_count += 1
        if args.task or args.dry_run:
            break
        if not args.auto_done:
            # Without --auto-done the finished task sits in `review`, so its dependants stay locked.
            nxt = eligible(parse_board(read_tasks_md()))
            if not nxt:
                print("Stopping: next tasks wait for review. Mark reviewed tasks `done (...)` or use --auto-done.")
                break
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show the status board summary and eligible tasks")
    r = sub.add_parser("run", help="run eligible tasks through OpenClaw")
    r.add_argument("--task", help="run this task ID only (ignores eligibility)")
    r.add_argument("--max", type=int, default=1, help="maximum tasks to run (default 1)")
    r.add_argument("--model", default=os.environ.get("OPENCLAW_MODEL", DEFAULT_MODEL),
                   help=f"provider/model for openclaw (default {DEFAULT_MODEL})")
    r.add_argument("--thinking", default="medium", help="openclaw thinking level (default medium)")
    r.add_argument("--timeout", type=int, default=3600, help="seconds per task (default 3600, 0 = none)")
    r.add_argument("--gateway", action="store_true", help="use the running gateway instead of --local")
    r.add_argument("--verify", help="custom verification shell command (default: pytest in services/tutor)")
    r.add_argument("--auto-done", action="store_true", help="mark passing tasks done instead of review")
    r.add_argument("--no-commit", action="store_true", help="do not git commit after a task")
    r.add_argument("--allow-dirty", action="store_true", help="allow starting with uncommitted changes")
    r.add_argument("--dry-run", action="store_true", help="write the prompt and print the command only")
    args = ap.parse_args()
    return cmd_status(args) if args.cmd == "status" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
