#!/usr/bin/env python3
"""Drive a coding agent through TASKS.md one task at a time.

Agents:
  copilot   (default) GitHub Copilot CLI in headless mode (npm install -g @github/copilot). It gets
            a short prompt pointing at specs/<ID>.md, so only tasks with a spec can run. It may
            use every tool except COPILOT_DENIED_TOOLS, and only on files inside the repository.
  claude    Claude Code in headless mode, pointed at the local Ollama server.
            It runs with --bare, so it never reads your Claude login or subscription: every
            model call goes to Ollama and counts against your Ollama plan only.
  openclaw  OpenClaw's embedded agent (`openclaw agent --local`), if installed.
  opencode  OpenCode in headless mode (`opencode run --auto`), default model NVIDIA Nemotron Ultra
            (env TASK_OPENCODE_MODEL). Like copilot it gets a short prompt pointing at
            specs/<ID>.md; OPENCODE_PERMISSIONS denies git writes, deletes, web access and files
            outside the repository.

Review checkpoint (owner decision D5): the runner never marks its own work done. Each run does
one task and stops:
  1. marks the task `in progress` on the TASKS.md status board,
  2. writes a prompt (TASKS.md sections 1-3, the task section, and any earlier review feedback)
     to .task-runs/<ID>/<time>/,
  3. runs the agent with that prompt, in the repository root,
  4. runs the test suite (pytest in services/tutor) if its venv exists,
  5. sets the status to `review (...)` and commits the work, or `blocked (...)` and leaves the work
     uncommitted for inspection.
Then Claude (in a Claude Code session with the owner) and the owner review the change:
  `review <ID>` builds the review packet, and `approve <ID>` or `reject <ID>` closes the
checkpoint. No new task starts while a task is waiting for review. Ollama models never review.

Usage:
    python tools/task_runner.py status                 # board summary + eligible tasks
    python tools/task_runner.py smoke                  # 1-minute check that agent + model work
    python tools/task_runner.py run --dry-run          # write the next prompt, print the command
    python tools/task_runner.py run                    # run the next eligible task, then stop
    python tools/task_runner.py run --task T10         # one specific task
    python tools/task_runner.py review T10             # build the review packet (diff, tests, reply)
    python tools/task_runner.py approve T10 --by "Claude + owner" --note "..."
    python tools/task_runner.py reject T10 --reason "what must change" [--revert]

Code written outside the runner (for example by GitHub Copilot from specs/<ID>.md) enters the same
checkpoint with `submit`: it runs the tests, commits the work as `[awaiting review]` and sets the
status to `review`:
    python tools/task_runner.py submit T01 --by "Copilot (<model>)" [--notes "what was done"]

Coordination between the coder and the reviewer, without anyone relaying messages. `wait` blocks,
polling the status board, until the other side has acted, then prints one line to act on:
    python tools/task_runner.py wait T10 --for review     # reviewer: until T10 is submitted
    python tools/task_runner.py wait T10 --for decision   # coder: until T10 is approved or rejected
Exit codes: 0 = act on the printed line, 2 = task blocked, 3 = timed out (run it again).

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
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TASKS_MD = REPO / "TASKS.md"
RUNS_DIR = REPO / ".task-runs"
TUTOR_DIR = REPO / "services" / "tutor"

DEFAULT_AGENT = os.environ.get("TASK_AGENT", "copilot")
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
# Copilot CLI runs with every tool allowed except these. Without --allow-all-paths it can only
# touch files under the repository, and without --allow-all-urls it cannot fetch web pages.
COPILOT_DENIED_TOOLS = [
    "shell(git push)", "shell(git commit)", "shell(git reset)", "shell(git checkout)",
    "shell(git restore)", "shell(git clean)", "shell(git rebase)", "shell(git remote)",
    "shell(git stash)", "shell(rm)", "shell(del)", "shell(Remove-Item)", "shell(curl)",
    "shell(Invoke-WebRequest)", "shell(Invoke-RestMethod)",
]
COPILOT_MODEL = os.environ.get("TASK_COPILOT_MODEL")  # unset: Copilot picks ("auto")
OPENCODE_MODEL = os.environ.get("TASK_OPENCODE_MODEL", "nvidia/nvidia/nemotron-3-ultra-550b-a55b")
# Passed as OPENCODE_CONFIG_CONTENT. `--auto` approves everything not denied here.
OPENCODE_PERMISSIONS = {
    "edit": "allow",
    "webfetch": "deny",
    "external_directory": "deny",
    "bash": {
        "*": "allow",
        **{f"{c}*": "deny" for c in (
            "git push", "git commit", "git reset", "git checkout", "git restore", "git clean",
            "git rebase", "git remote", "git stash", "rm ", "del ", "Remove-Item", "curl",
            "Invoke-WebRequest", "Invoke-RestMethod", "python tools/task_runner.py")},
    },
}
SPEC_AGENTS = ("copilot", "opencode")  # agents that get the spec prompt, not TASKS.md


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

# Copilot gets the spec, not TASKS.md: the spec is binding and .github/copilot-instructions.md
# (which Copilot CLI loads by itself) holds the project rules.
COPILOT_TEMPLATE = """You are GitHub Copilot working in the repository at:
{repo}

Your task: {id} - {title}
Implement specs/{id}.md exactly. Its "Prompt for Copilot" block is your instruction, and the spec
is binding. Follow .github/copilot-instructions.md, except its "When you finish" section: in this
run do not run task_runner.py submit or wait. Files from an earlier, unfinished attempt may
already exist: check them against the spec, keep what fits and finish the rest.

Rules for this run:
- Do only this task. Do not edit TASKS.md, specs/ or .github/.
- Do not commit, push or add git remotes. The runner commits your work.
- Create and edit files with your file-edit tools, never from the terminal.
- Some shell commands are refused. If a refused command is essential, stop and report BLOCKED
  with the command you needed.
- Run the spec's "Done when" commands and report their real output. Never claim a check passed
  without running it.
- When you are finished, write one line to the file {result_file}
  and also end your reply with that same line: "RESULT: DONE", or "RESULT: BLOCKED" followed by a
  one-line reason.
"""


OPENCODE_TEMPLATE = """You are a coding agent working in the repository at:
{repo}

Your task: {id} - {title}
Implement specs/{id}.md exactly. Its "Prompt for the agent" block is your instruction, and the spec
is binding. Read .github/copilot-instructions.md first and follow its rules, except its "When you
finish" section: do not run task_runner.py submit or wait. Files from an earlier, unfinished
attempt may already exist: check them against the spec, keep what fits and finish the rest.

Rules for this run:
- Do only this task. Do not edit TASKS.md, specs/, tools/ or .github/.
- Do not commit, push or add git remotes. The runner commits your work.
- Run Python only through services/tutor/.venv (for example
  `cd services/tutor && .venv/Scripts/python -m pytest -q`). Never pip install into another Python.
- Some shell commands are refused. If a refused command is essential, stop and report BLOCKED
  with the command you needed.
- Run the spec's "Done when" commands and report their real output. Never claim a check passed
  without running it.
- When you are finished, write one line to the file {result_file}
  and also end your reply with that same line: "RESULT: DONE", or "RESULT: BLOCKED" followed by a
  one-line reason.
"""


def feedback_file(task_id: str) -> Path:
    return RUNS_DIR / task_id / "feedback.md"


def spec_text(task_id: str) -> str | None:
    path = REPO / "specs" / f"{task_id}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


def delegated(task_id: str) -> bool:
    """True when specs/<ID>.md exists and does not reserve the task for Claude (D8)."""
    text = spec_text(task_id)
    return text is not None and "**Coder: Claude**" not in text


def spec_verify(task_id: str) -> str | None:
    """The command on the spec's **Verify:** line, if any."""
    m = re.search(r"^\*\*Verify:\*\*\s*`([^`]+)`", spec_text(task_id) or "", flags=re.M)
    return m.group(1) if m else None


def build_prompt(text: str, row: dict, result_file: Path, agent: str = "claude") -> str:
    if agent in SPEC_AGENTS:
        if not delegated(row["id"]):
            sys.exit(f"{row['id']} is not delegated: it needs specs/{row['id']}.md without "
                     "'Coder: Claude' (D8).")
        template = COPILOT_TEMPLATE if agent == "copilot" else OPENCODE_TEMPLATE
        prompt = template.format(repo=REPO, id=row["id"], title=row["title"], result_file=result_file)
    else:
        prompt = PROMPT_TEMPLATE.format(
            repo=REPO, id=row["id"], title=row["title"], result_file=result_file,
            shared=shared_sections(text), section=task_section(text, row["id"]),
        )
    fb = feedback_file(row["id"])
    if fb.exists():
        prompt += ("\n===== Review feedback on earlier attempts (fix every point) =====\n"
                   + fb.read_text(encoding="utf-8"))
    return prompt


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


def find_opencode() -> str | None:
    """The real binary: the npm .cmd shim mangles arguments through cmd.exe."""
    shim = shutil.which("opencode")
    if shim and shim.lower().endswith((".cmd", ".ps1")):
        exe = Path(shim).parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
        if exe.exists():
            return str(exe)
    return shim


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


def agent_label(args) -> str:
    """How the agent appears on the status board and in commit messages."""
    if args.agent == "copilot":
        return f"Copilot CLI ({args.model or 'auto'})"
    if args.agent == "opencode":
        return f"OpenCode ({args.model.rsplit('/', 1)[-1]})"
    return f"{args.agent} {args.model}"


def agent_command(args, session_id: str, prompt_path: Path) -> tuple[list[str], dict | None, str | None]:
    """Return (command, env, stdin_text)."""
    if args.agent == "copilot":
        # The prompt stays in a file: a long -p argument would hit the Windows command-line limit.
        cmd = [shutil.which("copilot") or "copilot", "-p",
               f"Read the file {prompt_path} and follow it exactly.",
               "-s", "--no-ask-user", "--no-color", "--allow-all-tools"]
        for tool in COPILOT_DENIED_TOOLS:
            cmd += ["--deny-tool", tool]
        if args.model:
            cmd += ["--model", args.model]
        return cmd, None, None
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
    if args.agent == "opencode":
        cmd = [find_opencode() or "opencode", "run", "--auto", "--model", args.model,
               f"Read the file {prompt_path} and follow it exactly."]
        env = dict(os.environ, OPENCODE_CONFIG_CONTENT=json.dumps({"permission": OPENCODE_PERMISSIONS}))
        return cmd, env, ""  # empty stdin: with an open pipe, `opencode run` waits for it to close
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


def git_commit(msg: str, paths: list[str] | None = None) -> str:
    """Commit `paths` (or everything) and return the short SHA, or a message starting 'no '."""
    if not is_git():
        return "no git repository"
    git("add", *(paths or ["-A"]))
    if not git("diff", "--cached", "--name-only").stdout.strip():
        return "no changes"
    proc = git("commit", "-m", msg)
    if proc.returncode != 0:
        return f"no commit: {proc.stderr.strip() or proc.stdout.strip()}"
    return git("rev-parse", "--short", "HEAD").stdout.strip()


def latest_run(task_id: str) -> Path | None:
    runs = sorted(p for p in (RUNS_DIR / task_id).glob("2*") if p.is_dir())
    return runs[-1] if runs else None


def pending_reviews(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["status"].startswith("review") and r["lane"] != "human"]


def ollama_models() -> list[str] | None:
    try:
        with urllib.request.urlopen(OLLAMA_HOST + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.loads(r.read().decode()).get("models", [])]
    except Exception:
        return None


def preflight(args) -> None:
    if args.agent == "copilot":
        if not shutil.which("copilot"):
            sys.exit("Copilot CLI not found. Install it: npm install -g @github/copilot")
        return
    if args.agent == "opencode":
        if not find_opencode():
            sys.exit("OpenCode not found. Install it: npm install -g opencode-ai")
        return
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
        f"Create the file {work / 'hello.txt'} containing the single word hello.\n"
        f"Then write the line RESULT: DONE to the file {result_file} and end your reply with that line.\n",
        encoding="utf-8")
    print(f"smoke test: {agent_label(args)} in {work}")
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
    prompt_path.write_text(build_prompt(text, row, result_file, args.agent), encoding="utf-8")
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
    set_status(row["id"], f"in progress ({agent_label(args)}, {today})")
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
        args.verify = args.verify or spec_verify(row["id"])
        passed, tail = verify(args, log_dir)
        print(f"    verify: {'pass' if passed else 'FAIL'} - {tail}")
        if not passed:
            ok, reason = False, f"tests failed after agent reported DONE: {tail}"

    rel = log_dir.relative_to(REPO).as_posix()
    if not ok:
        set_status(row["id"], f"blocked ({reason}; log {rel})")
        print(f"    status: blocked ({reason})")
        print("    left uncommitted for inspection")
        return False

    set_status(row["id"], f"review ({agent_label(args)}, {today}, log {rel})")
    sha = git_commit(f"{row['id']}: {row['title']} [awaiting review]\n\n"
                     f"Automated run: {agent_label(args)}. Not reviewed yet.")
    (log_dir / "commit.txt").write_text(sha, encoding="utf-8")
    print(f"    status: review  commit: {sha}")
    print(f"    CHECKPOINT: review before anything else runs:  python tools/task_runner.py review {row['id']}")
    return True


def cmd_run(args) -> int:
    rows = parse_board(read_tasks_md())
    waiting = pending_reviews(rows)
    if waiting and not args.dry_run and not args.stack:
        ids = ", ".join(r["id"] for r in waiting)
        sys.exit(f"Checkpoint: {ids} waiting for review. Run `review <ID>`, then `approve <ID>` or "
                 "`reject <ID> --reason ...` before starting another task.")
    if not args.dry_run:
        preflight(args)
        if is_git() and dirty() and not args.allow_dirty:
            sys.exit("Working tree has uncommitted changes. Commit or stash them, or pass --allow-dirty.")
    if args.task:
        row = next((r for r in rows if r["id"] == args.task), None)
        if row is None:
            sys.exit(f"{args.task} is not on the status board")
        if row["lane"] == "human":
            sys.exit(f"{args.task} is a human task")
    else:
        el = eligible(rows)
        if args.agent in SPEC_AGENTS:
            el = [r for r in el if delegated(r["id"])]
        if not el:
            print("Nothing eligible for this agent. Run `status` to see what is blocked or waiting.")
            return 0
        row = el[0]
    return 0 if run_one(args, row) else 1


def cmd_submit(args) -> int:
    """Put work written outside the runner (e.g. by Copilot) through the review checkpoint."""
    rows = parse_board(read_tasks_md())
    row = next((r for r in rows if r["id"] == args.task_id), None)
    if row is None:
        sys.exit(f"{args.task_id} is not on the status board")
    if row["lane"] == "human":
        sys.exit(f"{args.task_id} is a human task")
    if row["status"].startswith(("done", "review")):
        sys.exit(f"{args.task_id} is already {row['status']}")
    waiting = [r["id"] for r in pending_reviews(rows) if r["id"] != row["id"]]
    if waiting:
        sys.exit(f"Checkpoint: {', '.join(waiting)} waiting for review. Close it first.")
    status = {r["id"]: r["status"] for r in rows}
    open_deps = [d for d in row["deps"] if not status.get(d, "").startswith("done")]
    if open_deps:
        sys.exit(f"{args.task_id} depends on {', '.join(open_deps)}, which are not done yet.")
    if not is_git():
        sys.exit("submit needs a git repository")
    if not dirty():
        sys.exit("No changes to submit. Let the coding agent write the task first.")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir = RUNS_DIR / row["id"] / stamp
    log_dir.mkdir(parents=True, exist_ok=True)
    passed, tail = verify(args, log_dir)
    print(f"    verify: {'pass' if passed else 'FAIL'} - {tail}")
    if not passed and not args.allow_failing:
        sys.exit(f"Tests fail, so {row['id']} was not submitted. Fix them first "
                 f"(output: {log_dir / 'verify.txt'}), or pass --allow-failing to review anyway.")
    (log_dir / "result.txt").write_text(f"RESULT: DONE (submitted by {args.by})\n", encoding="utf-8")
    (log_dir / "reply.md").write_text(args.notes or f"Submitted by {args.by}. No agent report.",
                                      encoding="utf-8")

    rel = log_dir.relative_to(REPO).as_posix()
    today = dt.date.today().isoformat()
    set_status(row["id"], f"review ({args.by}, {today}, log {rel})")
    sha = git_commit(f"{row['id']}: {row['title']} [awaiting review]\n\n"
                     f"Written by {args.by}. Tests: {tail}. Not reviewed yet.")
    (log_dir / "commit.txt").write_text(sha, encoding="utf-8")
    print(f"    status: review  commit: {sha}")
    print(f"    CHECKPOINT: ask Claude to review {row['id']}  (python tools/task_runner.py review {row['id']})")
    return 0


def next_spec_task(rows: list[dict]) -> dict | None:
    """First eligible task (board order) that has a code spec in specs/."""
    return next((r for r in eligible(rows) if (REPO / "specs" / f"{r['id']}.md").exists()), None)


def cmd_wait(args) -> int:
    """Block until the other side of the checkpoint has acted, then print what to do next."""
    def status() -> str:
        row = next((r for r in parse_board(read_tasks_md()) if r["id"] == args.task_id), None)
        if row is None:
            sys.exit(f"{args.task_id} is not on the status board")
        return row["status"]

    start = status()
    if args.for_ == "decision" and not start.startswith("review"):
        sys.exit(f"{args.task_id} is not waiting for review (status: {start}). Submit it first.")
    deadline = time.monotonic() + args.timeout if args.timeout else None
    print(f"waiting for {args.for_} on {args.task_id} (status: {start}; every {args.interval}s)", flush=True)
    while True:
        s = status()
        if s.startswith("blocked"):
            print(f"BLOCKED {args.task_id}: {s}", flush=True)
            return 2
        if args.for_ == "review" and s.startswith("done"):
            print(f"DONE {args.task_id}: already approved ({s})", flush=True)
            return 0
        if args.for_ == "review" and s.startswith("review"):
            print(f"SUBMITTED {args.task_id}: review it now (python tools/task_runner.py review {args.task_id})",
                  flush=True)
            return 0
        if args.for_ == "decision" and s.startswith("done"):
            nxt = next_spec_task(parse_board(read_tasks_md()))
            follow = (f"NEXT {nxt['id']}: implement specs/{nxt['id']}.md" if nxt
                      else "NEXT none: no eligible task has a spec yet; stop and tell the owner")
            print(f"APPROVED {args.task_id}. {follow}", flush=True)
            return 0
        if args.for_ == "decision" and s.startswith("todo"):
            print(f"REJECTED {args.task_id}: fix every point in .task-runs/{args.task_id}/feedback.md, "
                  f"then submit again", flush=True)
            return 0
        if deadline and time.monotonic() >= deadline:
            print(f"TIMEOUT {args.task_id}: still {s}; run the same wait command again", flush=True)
            return 3
        time.sleep(args.interval)


# --------------------------------------------------------------------------- #
# Review checkpoint
# --------------------------------------------------------------------------- #
REVIEW_CHECKLIST = """## Reviewer checklist (Claude + owner; Ollama models never review)

- [ ] The change does exactly this task: nothing missing, nothing from other tasks.
- [ ] Every acceptance check in the task section was run, and the output below proves it.
- [ ] The invariants in TASKS.md section 2 hold: code owns the flow, deterministic selection,
      temperature-0 structured grading, append-only ledger, cite or refuse, no similarity search in
      grading, no invented ground truth, answer key never reaches the tutor, content is data,
      distraction-free kiosk, stable node IDs.
- [ ] Domain content (rubrics, explanations, examples, calculations) is correct against the official
      sources. Any doubt goes to the owner.
- [ ] Tests are meaningful: they would fail if the feature broke.
- [ ] No secrets, licensed source text or personal data were committed.

Decision: `approve <ID> --by ... --note ...` or `reject <ID> --reason ...` (add `--revert` to undo
the commit).
"""


def _review_row(task_id: str) -> tuple[dict, Path, str]:
    rows = parse_board(read_tasks_md())
    row = next((r for r in rows if r["id"] == task_id), None)
    if row is None:
        sys.exit(f"{task_id} is not on the status board")
    if not row["status"].startswith("review"):
        sys.exit(f"{task_id} is not waiting for review (status: {row['status']})")
    run_dir = latest_run(task_id)
    if run_dir is None or not (run_dir / "commit.txt").exists():
        sys.exit(f"No runner commit recorded for {task_id} under {RUNS_DIR / task_id}")
    return row, run_dir, (run_dir / "commit.txt").read_text(encoding="utf-8").strip()


def _tail(path: Path, n: int) -> str:
    if not path.exists():
        return "(missing)"
    lines = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return "\n".join(lines[-n:]) or "(empty)"


def cmd_review(args) -> int:
    row, run_dir, sha = _review_row(args.task_id)
    stat = git("show", "--stat", "--format=%H%n%s%n", sha).stdout if is_git() else "(no git)"
    diff = git("show", "--format=", sha).stdout if is_git() else ""
    (run_dir / "diff.patch").write_text(diff, encoding="utf-8")
    rel = run_dir.relative_to(REPO).as_posix()
    packet = (
        f"# Review packet: {row['id']} - {row['title']}\n\n"
        f"- Status: {row['status']}\n- Commit: `{sha}`\n- Run folder: `{rel}`\n"
        f"- Full diff: `{rel}/diff.patch` ({len(diff.splitlines())} lines)\n\n"
        f"## Agent result\n\n```\n{_tail(run_dir / 'result.txt', 3)}\n```\n\n"
        f"## Agent reply (last 40 lines)\n\n```\n{_tail(run_dir / 'reply.md', 40)}\n```\n\n"
        f"## Runner test run (last 15 lines)\n\n```\n{_tail(run_dir / 'verify.txt', 15)}\n```\n\n"
        f"## Files changed\n\n```\n{stat.strip()}\n```\n\n"
        f"## Task as specified\n\n{task_section(read_tasks_md(), row['id'])}\n\n"
        f"{REVIEW_CHECKLIST}"
    )
    out = run_dir / "review.md"
    out.write_text(packet, encoding="utf-8")
    print(f"Review packet: {out}")
    print(f"Diff:          {run_dir / 'diff.patch'}")
    print(stat.strip())
    return 0


def cmd_approve(args) -> int:
    row, run_dir, sha = _review_row(args.task_id)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    (run_dir / "approval.md").write_text(
        f"Approved {stamp} by {args.by}\nCommit: {sha}\nNote: {args.note or '-'}\n", encoding="utf-8")
    set_status(row["id"], f"done ({sha}, reviewed by {args.by})")
    msg = f"{row['id']}: approved at review checkpoint\n\nReviewed by {args.by}. {args.note or ''}".strip()
    res = git_commit(msg, ["TASKS.md"])
    print(f"{row['id']} approved. Status: done ({sha}). Commit: {res}")
    return 0


def cmd_reject(args) -> int:
    row, run_dir, sha = _review_row(args.task_id)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    fb = feedback_file(row["id"])
    fb.parent.mkdir(parents=True, exist_ok=True)
    with fb.open("a", encoding="utf-8") as fh:
        fh.write(f"\n### Review of commit {sha} ({stamp}, {args.by})\n{args.reason.strip()}\n"
                 + ("The commit was reverted; start again from the current code.\n" if args.revert
                    else "The commit was kept; fix it in place.\n"))
    paths = ["TASKS.md"]
    if args.revert and is_git():
        proc = git("revert", "--no-edit", sha)
        if proc.returncode != 0:
            sys.exit(f"git revert failed: {proc.stderr.strip()}")
        paths = None
    set_status(row["id"], "todo")
    res = git_commit(f"{row['id']}: rejected at review checkpoint\n\n{args.reason.strip()}", paths)
    print(f"{row['id']} rejected and set back to todo. Feedback saved to {fb} "
          f"and added to the next prompt. Commit: {res}")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show the status board summary and eligible tasks")

    def agent_opts(p):
        p.add_argument("--agent", choices=["copilot", "claude", "openclaw", "opencode"], default=DEFAULT_AGENT,
                       help=f"coding agent (default {DEFAULT_AGENT}; env TASK_AGENT)")
        p.add_argument("--model", help=f"copilot: Copilot model (default auto; env TASK_COPILOT_MODEL); "
                                       f"claude/openclaw: Ollama model (default {DEFAULT_MODEL}; env TASK_MODEL)")
        p.add_argument("--timeout", type=int, default=3600, help="seconds per task (default 3600, 0 = none)")
        p.add_argument("--thinking", default="medium", help="openclaw thinking level (default medium)")
        p.add_argument("--yolo", action="store_true", help="claude: allow every command (disposable checkouts only)")

    agent_opts(sub.add_parser("smoke", help="check that the agent and model can edit a file"))
    r = sub.add_parser("run", help="run the next eligible task, then stop at the review checkpoint")
    agent_opts(r)
    r.add_argument("--task", help="run this task ID only (ignores eligibility)")
    r.add_argument("--verify", help="custom verification shell command (default: pytest in services/tutor)")
    r.add_argument("--allow-dirty", action="store_true", help="allow starting with uncommitted changes")
    r.add_argument("--dry-run", action="store_true", help="write the prompt and print the command only")
    r.add_argument("--stack", action="store_true",
                   help="run although other tasks wait for review; the new task builds on unreviewed "
                        "code, so use it only on a disposable trial branch")
    sb = sub.add_parser("submit", help="send work written outside the runner (e.g. Copilot) to the checkpoint")
    sb.add_argument("task_id")
    sb.add_argument("--by", required=True, help="who wrote the code, e.g. 'Copilot (GPT-5)'")
    sb.add_argument("--notes", help="short report of what was done; shown in the review packet")
    sb.add_argument("--verify", help="custom verification shell command (default: pytest in services/tutor)")
    sb.add_argument("--allow-failing", action="store_true", help="submit even if the tests fail")
    wt = sub.add_parser("wait", help="block until the task is submitted (--for review) or decided (--for decision)")
    wt.add_argument("task_id")
    wt.add_argument("--for", dest="for_", choices=["review", "decision"], required=True)
    wt.add_argument("--timeout", type=int, default=1800, help="seconds before giving up (default 1800, 0 = none)")
    wt.add_argument("--interval", type=int, default=20, help="seconds between checks (default 20)")
    rv = sub.add_parser("review", help="build the review packet for a task waiting at the checkpoint")
    rv.add_argument("task_id")
    apv = sub.add_parser("approve", help="close the checkpoint: mark the task done")
    apv.add_argument("task_id")
    apv.add_argument("--by", default="Claude + owner", help="who reviewed (default 'Claude + owner')")
    apv.add_argument("--note", help="short review note")
    rj = sub.add_parser("reject", help="close the checkpoint: send the task back with feedback")
    rj.add_argument("task_id")
    rj.add_argument("--reason", required=True, help="what must change; added to the next prompt")
    rj.add_argument("--by", default="Claude + owner")
    rj.add_argument("--revert", action="store_true", help="also git-revert the task commit")
    args = ap.parse_args()
    if hasattr(args, "agent") and args.model is None:
        args.model = {"copilot": COPILOT_MODEL, "opencode": OPENCODE_MODEL}.get(args.agent, DEFAULT_MODEL)
    return {"status": cmd_status, "smoke": cmd_smoke, "run": cmd_run, "submit": cmd_submit,
            "wait": cmd_wait, "review": cmd_review, "approve": cmd_approve,
            "reject": cmd_reject}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
