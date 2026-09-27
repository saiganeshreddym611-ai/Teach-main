#!/usr/bin/env python3
"""Drive a coding agent, backed by an Ollama model, through TASKS.md one task at a time.

Agents:
  claude    (default) Claude Code in headless mode, pointed at the local Ollama server.
            It runs with --bare, so it never reads your Claude login or subscription: every
            model call goes to Ollama and counts against your Ollama plan only.
  openclaw  OpenClaw's embedded agent (`openclaw agent --local`), if installed.

For each eligible task (status `todo`, not a human task, every dependency `done`) the runner:
  1. marks it `in progress` on the TASKS.md status board,
  2. writes a prompt (TASKS.md sections 1-3 + the task section) to .task-runs/<ID>/<time>/,
  3. runs the agent with that prompt, in the repository root,
  4. runs the test suite (pytest in services/tutor) if its venv exists,
  5. sets the status to `review` (or `done` with --auto-done) or `blocked (...)`,
  6. commits the result.
It stops at the first task that does not finish cleanly and leaves that work uncommitted.

Usage:
    python tools/task_runner.py status                 # board summary + eligible tasks
    python tools/task_runner.py smoke                  # 1-minute check that agent + model work
    python tools/task_runner.py run --dry-run          # write the next prompt, print the command
    python tools/task_runner.py run                    # run the next eligible task
    python tools/task_runner.py run --max 5 --auto-done   # chain tasks without human review
    python tools/task_runner.py run --task T10         # one specific task

Permissions (claude): file edits are allowed; shell commands only from an allowlist (git without
push/commit/reset, python, pip, pytest, npm, node, basic file inspection). Anything else is
refused automatically. --yolo allows every command; use it only in a disposable checkout.

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
RUNS_DIR = REPO / ".task-runs"
TUTOR_DIR = REPO / "services" / "tutor"

DEFAULT_AGENT = os.environ.get("TASK_AGENT", "claude")
DEFAULT_MODEL = os.environ.get("TASK_MODEL", "gemma4:31b-cloud")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not OLLAMA_HOST.startswith("http"):
    OLLAMA_HOST = "http://" + OLLAMA_HOST

ROW_RE = re.compile(
    r"^\|\s*(?P<id>T\d{2,3}|H\d+)\s*\|(?P<title>[^|]*)\|(?P<lane>[^|]*)\|(?P<deps>[^|]*)\|(?P<status>[^|]*)\|\s*$"
)
RESULT_RE = re.compile(r"RESULT:\s*(DONE|BLOCKED)\b[ \t]*([^\n\"\\]*)")

CLAUDE_ALLOWED_TOOLS = [
    "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite",
    "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
    "Bash(git add:*)", "Bash(git mv:*)", "Bash(git rm:*)", "Bash(git ls-files:*)", "Bash(git init:*)",
    "Bash(python:*)", "Bash(py:*)", "Bash(pip:*)", "Bash(pytest:*)",
    "Bash(.venv/Scripts/python:*)", "Bash(.venv/Scripts/python.exe:*)", "Bash(.venv/bin/python:*)",
    "Bash(services/tutor/.venv/Scripts/python:*)", "Bash(services/tutor/.venv/Scripts/python.exe:*)",
    "Bash(npm:*)", "Bash(npx:*)", "Bash(node:*)",
    "Bash(cd:*)", "Bash(ls:*)", "Bash(pwd)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)",
    "Bash(wc:*)", "Bash(grep:*)", "Bash(find:*)", "Bash(mkdir:*)", "Bash(cp:*)", "Bash(mv:*)",
    "Bash(echo:*)", "Bash(sort:*)", "Bash(diff:*)", "Bash(touch:*)",
]
CLAUDE_DENIED_TOOLS = [
    "Bash(git push:*)", "Bash(git remote:*)", "Bash(git commit:*)", "Bash(git reset:*)",
    "Bash(git checkout:*)", "Bash(git restore:*)", "Bash(git clean:*)", "Bash(git rebase:*)",
    "Bash(rm -rf:*)", "WebFetch", "WebSearch",
]


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
        rows.append({"id": m["id"], "title": m["title"].strip(), "lane": m["lane"].strip(),
                     "deps": deps, "status": m["status"].strip()})
    if not rows:
        sys.exit("No status board rows found in TASKS.md (section '## 4. Status board').")
    return rows


def eligible(rows: list[dict]) -> list[dict]:
    status = {r["id"]: r["status"] for r in rows}
    return [
        r for r in rows
        if r["status"] == "todo" and r["lane"] != "human"
        and all(status.get(d, "").startswith("done") for d in r["deps"])
    ]


def set_status(task_id: str, new_status: str) -> None:
    """Rewrite one status cell. Re-reads the file so edits made by the agent survive."""
    new_status = new_status.replace("|", "/").replace("\n", " ").strip()
    lines = read_tasks_md().split("\n")
    for i, line in enumerate(lines):
        m = ROW_RE.match(line.rstrip("\r"))
        if m and m["id"] == task_id:
            cr = "\r" if line.endswith("\r") else ""
            lines[i] = (f"| {m['id']} | {m['title'].strip()} | {m['lane'].strip()} | "
                        f"{m['deps'].strip()} | {new_status} |{cr}")
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
    start, end = text.find("## 1. How to use this file"), text.find("## 4. Status board")
    return text[start:end].strip() if start != -1 and end != -1 else ""


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #
PROMPT_TEMPLATE = """You are a coding agent working in the repository at:
{repo}

Use paths inside that directory for every file operation. Run every shell command with that
directory (or a subdirectory of it) as the working directory. Do not touch files outside it.

Your task: {id} - {title}

Before you start, read REQUIREMENTS.md, README.md and HUMAN-DECISIONS.md in the repository, then
every file the task lists under "Read first".

Rules for this run:
- Do only this task. Do not start other tasks.
- Do not edit the status board (section 4) in TASKS.md. The runner updates it. You may append rows
  to the Open questions log (section 10).
- Do not push, do not add git remotes and do not commit. The runner commits your work.
- Some shell commands are not permitted and will be refused. If a refused command is essential,
  stop and report BLOCKED with the command you needed.
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


# --------------------------------------------------------------------------- #
# Agents
# --------------------------------------------------------------------------- #
def find_claude() -> str | None:
    exe = shutil.which("claude")
    if exe:
        return exe
    # Fall back to the binary bundled with the VS Code extension (newest version first).
    ext_root = Path.home() / ".vscode" / "extensions"
    name = "claude.exe" if os.name == "nt" else "claude"
    candidates = sorted(ext_root.glob(f"anthropic.claude-code-*/resources/native-binary/{name}"),
                        key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", p.parts[-4])],
                        reverse=True)
    return str(candidates[0]) if candidates else None


def claude_env(model: str) -> dict:
    env = dict(os.environ)
    for k in ("ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
              "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        env.pop(k, None)
    env.update({
        "ANTHROPIC_BASE_URL": OLLAMA_HOST,   # every model call goes to Ollama
        "ANTHROPIC_API_KEY": "ollama",       # --bare reads only this; Ollama ignores its value
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        "ANTHROPIC_SMALL_FAST_MODEL": model,
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
    })
    return env


def agent_command(args, session_id: str, prompt_path: Path) -> tuple[list[str], dict | None, str | None]:
    """Return (command, env, stdin_text)."""
    if args.agent == "claude":
        exe = find_claude() or "claude"
        cmd = [exe, "-p", "--bare", "--strict-mcp-config", "--disable-slash-commands",
               "--no-session-persistence", "--model", args.model, "--output-format", "json"]
        if args.yolo:
            cmd += ["--permission-mode", "bypassPermissions"]
        else:
            cmd += ["--permission-mode", "acceptEdits", "--permission-prompts", "none",
                    "--allowedTools", *CLAUDE_ALLOWED_TOOLS]
        cmd += ["--disallowedTools", *CLAUDE_DENIED_TOOLS]
        return cmd, claude_env(args.model), prompt_path.read_text(encoding="utf-8")
    exe = shutil.which("openclaw") or "openclaw"
    model = args.model if "/" in args.model else "ollama/" + args.model
    cmd = [exe, "agent", "--local", "--session-id", session_id, "--message-file", str(prompt_path),
           "--model", model, "--thinking", args.thinking, "--timeout", str(args.timeout), "--json"]
    return cmd, None, None


def run_agent(args, cwd: Path, log_dir: Path, prompt_path: Path, session_id: str) -> tuple[int, str]:
    cmd, env, stdin_text = agent_command(args, session_id, prompt_path)
    proc = subprocess.run(cmd, cwd=cwd, env=env, input=stdin_text, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=(args.timeout + 120) if args.timeout else None)
    (log_dir / "stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (log_dir / "stderr.txt").write_text(proc.stderr, encoding="utf-8")
    out = proc.stdout
    if args.agent == "claude":
        try:
            data = json.loads(proc.stdout)
            out = str(data.get("result") or "")
            (log_dir / "reply.md").write_text(out, encoding="utf-8")
            meta = {k: data.get(k) for k in ("is_error", "subtype", "num_turns", "duration_ms")}
            (log_dir / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            if data.get("is_error") and proc.returncode == 0:
                return 1, out
        except (json.JSONDecodeError, AttributeError):
            pass
    return proc.returncode, out


def find_result(result_file: Path, reply: str) -> tuple[str, str]:
    """("DONE"|"BLOCKED"|"UNKNOWN", reason). Prefers the result file the agent writes."""
    if result_file.exists():
        hits = RESULT_RE.findall(result_file.read_text(encoding="utf-8", errors="replace"))
        if hits:
            return hits[-1][0], hits[-1][1].strip()
    marker = reply.rfind("Your task =====")
    hits = RESULT_RE.findall(reply[marker:] if marker != -1 else reply)
    if not hits:
        return "UNKNOWN", "agent reported no RESULT line"
    return hits[-1][0], hits[-1][1].strip()


# --------------------------------------------------------------------------- #
# Verification, git, preflight
# --------------------------------------------------------------------------- #
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


def is_git() -> bool:
    return (REPO / ".git").exists()


def git(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def dirty() -> bool:
    return bool(git("status", "--porcelain").stdout.strip())


def commit(row: dict, args) -> str:
    if not is_git() or not dirty():
        return "nothing to commit"
    git("add", "-A")
    msg = f"{row['id']}: {row['title']}\n\nAutomated run: {args.agent} with {args.model} via Ollama."
    proc = git("commit", "-m", msg)
    if proc.returncode != 0:
        return f"commit failed: {proc.stderr.strip() or proc.stdout.strip()}"
    return git("rev-parse", "--short", "HEAD").stdout.strip()


def ollama_models() -> list[str] | None:
    try:
        with urllib.request.urlopen(OLLAMA_HOST + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.loads(r.read().decode()).get("models", [])]
    except Exception:
        return None


def preflight(args) -> None:
    if args.agent == "claude" and not find_claude():
        sys.exit("Claude Code not found. Install it (npm install -g @anthropic-ai/claude-code) "
                 "or install the Claude Code VS Code extension.")
    if args.agent == "openclaw" and not shutil.which("openclaw"):
        sys.exit("openclaw not found on PATH. Run: ollama launch openclaw --model gemma4:31b-cloud --yes")
    models = ollama_models()
    if models is None:
        sys.exit(f"Ollama is not answering at {OLLAMA_HOST}. Start Ollama first.")
    bare = args.model.split("/", 1)[-1]
    if bare not in models:
        print(f"warning: {bare} is not in Ollama's model list {models}. Run: ollama pull {bare}")


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
            print(f"  {r['id']:5} {r['status']}")
    el = eligible(rows)
    print("Eligible now:" if el else "Nothing eligible (check blocked tasks and human tasks).")
    for r in el:
        print(f"  {r['id']:5} {r['title']}")
    return 0


def cmd_smoke(args) -> int:
    """Tiny end-to-end check: the agent must create a file and report DONE."""
    preflight(args)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    work = RUNS_DIR / "smoke" / stamp
    work.mkdir(parents=True, exist_ok=True)
    result_file = work / "result.txt"
    prompt_path = work / "prompt.md"
    prompt_path.write_text(
        "Create a file named hello.txt in the current directory containing the single word hello.\n"
        f"Then write the line RESULT: DONE to the file {result_file} and end your reply with that line.\n",
        encoding="utf-8")
    print(f"smoke test: {args.agent} + {args.model} in {work}")
    started = dt.datetime.now()
    code, reply = run_agent(args, work, work, prompt_path, f"smoke-{stamp}")
    secs = (dt.datetime.now() - started).total_seconds()
    kind, _ = find_result(result_file, reply)
    hello = (work / "hello.txt")
    ok = code == 0 and kind == "DONE" and hello.exists() and "hello" in hello.read_text(encoding="utf-8").lower()
    print(f"  exit={code} result={kind} hello.txt={'yes' if hello.exists() else 'no'} time={secs:.0f}s")
    print("  PASS: the runner is ready." if ok else f"  FAIL: see {work} (stdout.txt, stderr.txt)")
    return 0 if ok else 1


def run_one(args, row: dict) -> bool:
    text = read_tasks_md()
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = RUNS_DIR / row["id"] / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    result_file = log_dir / "result.txt"
    prompt_path = log_dir / "prompt.md"
    prompt_path.write_text(build_prompt(text, row, result_file), encoding="utf-8")
    session_id = f"teach-{row['id']}-{stamp}"

    if args.dry_run:
        cmd, _, stdin_text = agent_command(args, session_id, prompt_path)
        print(f"[dry-run] {row['id']} - {row['title']}")
        print(f"[dry-run] prompt: {prompt_path} ({prompt_path.stat().st_size:,} bytes)")
        shown = subprocess.list2cmdline(cmd)
        print("[dry-run] command:", shown[:600] + (" ..." if len(shown) > 600 else ""))
        if stdin_text:
            print("[dry-run] the prompt is sent on stdin")
        return True

    today = dt.date.today().isoformat()
    set_status(row["id"], f"in progress ({args.agent} {args.model}, {today})")
    print(f"==> {row['id']} - {row['title']}  (log: {log_dir.relative_to(REPO).as_posix()})")
    try:
        code, reply = run_agent(args, REPO, log_dir, prompt_path, session_id)
        kind, reason = find_result(result_file, reply)
        if code != 0 and kind != "BLOCKED":
            kind, reason = "BLOCKED", f"{args.agent} exited {code}"
    except subprocess.TimeoutExpired:
        kind, reason = "BLOCKED", f"{args.agent} timed out"
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
        status = f"done ({args.agent}, {today})" if args.auto_done else f"review ({args.agent} {args.model}, {today}, log {rel})"
    else:
        status = f"blocked ({reason}; log {rel})"
    set_status(row["id"], status)
    print(f"    status: {status}")
    if ok and not args.no_commit:
        print(f"    commit: {commit(row, args)}")
    elif not ok:
        print("    left uncommitted for inspection")
    return ok


def cmd_run(args) -> int:
    if not args.dry_run:
        preflight(args)
        if is_git() and dirty() and not args.allow_dirty:
            sys.exit("Working tree has uncommitted changes. Commit or stash them, or pass --allow-dirty.")
    count = 0
    while count < args.max:
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
                print("Nothing eligible. Run `status` to see what is blocked or waiting for review.")
                break
            row = el[0]
        if not run_one(args, row):
            return 1
        count += 1
        if args.task or args.dry_run:
            break
        if not args.auto_done and not eligible(parse_board(read_tasks_md())):
            print("Stopping: next tasks wait for review. Mark reviewed tasks `done (...)` or use --auto-done.")
            break
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show the status board summary and eligible tasks")

    def agent_opts(p):
        p.add_argument("--agent", choices=["claude", "openclaw"], default=DEFAULT_AGENT,
                       help=f"coding agent (default {DEFAULT_AGENT}; env TASK_AGENT)")
        p.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default {DEFAULT_MODEL}; env TASK_MODEL)")
        p.add_argument("--timeout", type=int, default=3600, help="seconds per task (default 3600, 0 = none)")
        p.add_argument("--thinking", default="medium", help="openclaw thinking level (default medium)")
        p.add_argument("--yolo", action="store_true", help="claude: allow every command (disposable checkouts only)")

    agent_opts(sub.add_parser("smoke", help="check that the agent and model can edit a file"))
    r = sub.add_parser("run", help="run eligible tasks")
    agent_opts(r)
    r.add_argument("--task", help="run this task ID only (ignores eligibility)")
    r.add_argument("--max", type=int, default=1, help="maximum tasks to run (default 1)")
    r.add_argument("--verify", help="custom verification shell command (default: pytest in services/tutor)")
    r.add_argument("--auto-done", action="store_true", help="mark passing tasks done instead of review")
    r.add_argument("--no-commit", action="store_true", help="do not git commit after a task")
    r.add_argument("--allow-dirty", action="store_true", help="allow starting with uncommitted changes")
    r.add_argument("--dry-run", action="store_true", help="write the prompt and print the command only")
    args = ap.parse_args()
    return {"status": cmd_status, "smoke": cmd_smoke, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
