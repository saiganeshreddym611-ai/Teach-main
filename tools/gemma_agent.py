#!/usr/bin/env python3
"""Hand grunt work to gemma4 on Ollama through Claude Code's headless harness.

Same tools as a Haiku subagent, but every model call goes to the local Ollama server (task_runner's
`claude` agent with --bare), so it costs nothing on the Claude plan. Claude still reviews the result:
Ollama models never review (D6).

    python tools/gemma_agent.py prompt.md                      # read-only: search, survey, summarise
    python tools/gemma_agent.py prompt.md --edit               # may edit files (mechanical edits, drafts)
    python tools/gemma_agent.py prompt.md --edit --cwd apps/web --allow "Bash(npm run lint:*)"

Prints one JSON line of metrics, then the agent's reply. Logs go to .task-runs/gemma/<time>/.
Measured 2026-09-27 against Haiku: same results on a code search (5/5) and a three-file web edit,
2.7x faster on the edit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_runner as tr  # noqa: E402

READ_ONLY_TOOLS = ["Read", "Glob", "Grep", "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)",
                   "Bash(git show:*)", "Bash(git ls-files:*)", "Bash(git grep:*)"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("prompt", type=Path, help="file holding the task prompt")
    p.add_argument("--edit", action="store_true", help="allow file edits (default: read-only)")
    p.add_argument("--cwd", type=Path, default=tr.REPO, help="working directory (default: repo root)")
    p.add_argument("--allow", action="append", default=[], help="extra allowed tool rule, e.g. \"Bash(npm test:*)\"")
    p.add_argument("--model", default=tr.DEFAULT_MODEL)
    p.add_argument("--timeout", type=int, default=1500)
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # replies contain ✓, → and similar

    if not tr.find_claude():
        sys.exit("Claude Code binary not found (PATH or the VS Code extension).")
    tr.CLAUDE_ALLOWED_TOOLS[:] = (tr.CLAUDE_ALLOWED_TOOLS if args.edit else READ_ONLY_TOOLS) + args.allow
    if not args.edit:
        tr.CLAUDE_DENIED_TOOLS[:] = tr.CLAUDE_DENIED_TOOLS + ["Edit", "Write", "NotebookEdit"]

    log = tr.RUNS_DIR / "gemma" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log.mkdir(parents=True, exist_ok=True)
    prompt = log / "prompt.md"
    shutil.copyfile(args.prompt, prompt)
    run_args = argparse.Namespace(agent="claude", model=args.model, yolo=False, timeout=args.timeout,
                                  thinking="medium", verify=None)
    code, reply = tr.run_agent(run_args, args.cwd.resolve(), log, prompt, f"gemma-{log.name}")
    metrics: dict = {"exit": code, "log": str(log)}
    try:
        data = json.loads((log / "stdout.txt").read_text(encoding="utf-8", errors="replace"))
        usage = data.get("usage") or {}
        metrics.update(turns=data.get("num_turns"), seconds=round((data.get("duration_ms") or 0) / 1000),
                       input=usage.get("input_tokens"), cache_read=usage.get("cache_read_input_tokens"),
                       output=usage.get("output_tokens"))
    except (OSError, json.JSONDecodeError):
        pass
    print(json.dumps(metrics))
    print(reply)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
