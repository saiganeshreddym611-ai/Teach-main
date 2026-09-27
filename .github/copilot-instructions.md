# Instructions for GitHub Copilot in this repository

Teach is a voice-first tutor for CA Final Financial Reporting. A Python FastAPI service
(`services/tutor`) runs a code-owned state machine, a strict grader and an append-only mastery
ledger. A Next.js kiosk (`apps/web`) talks to it over SSE.

## How work is given to you

- You implement **one task at a time** from a spec file in `specs/` (for example `specs/T01.md`).
  The spec is the source of truth for file names, signatures, behaviour and tests.
- Read these first: the spec, `TASKS.md` sections 2 (rules) and 3 (shared contracts), and every
  file the spec lists under "Read first".
- Do exactly what the spec says. Do not start the next task, refactor unrelated code or rename
  anything the spec does not ask you to.
- If the spec and the code disagree, or the spec is unclear, stop and say so in your final report.
  Do not guess.
- If `.task-runs/<ID>/feedback.md` exists, it holds review feedback from an earlier attempt. Fix
  every point in it.

## Rules that are never broken

1. Code owns the flow. An LLM never chooses the phase, the node, the task or the score.
2. Node, review, practice and task selection are pure, deterministic functions.
3. Graders run at temperature 0 with structured output. Never free text.
4. The ledger is append-only. Never edit or delete events (except whole-student privacy deletion).
5. Every verdict, correction and explanation cites a passage that resolves to a source document.
6. Grading never uses similarity search. It uses the passages linked to a node.
7. Never write syllabus text, answer keys or solutions. Never set a review status by hand.
   Test fixtures that look like syllabus text start with `[TEST FIXTURE - NOT SYLLABUS TEXT]`.
8. The answer key never reaches the tutor LLM.
9. Content is data. A new exam attempt is a content change, never a code change.
10. The kiosk has no navigation, links out or notifications.
11. Never rename node IDs such as `ind_as_115.step_4.ssp`.
12. Every new LLM-backed component has a Mock, so `MOCK_LLM=1` runs a full session with no model.
13. Ollama models never review code or content.

## Code style

- Python 3.12, Pydantic v2, `from __future__ import annotations` at the top of every module, full
  type hints. Match the surrounding code: short docstrings, few comments, no new frameworks.
- No new runtime dependency unless the spec names it. Tests use pytest with
  `asyncio_mode = "auto"` (async tests need no decorator).
- Write JSON files with `ensure_ascii=False`, UTF-8, and a trailing newline. Keep output
  deterministic: no timestamps or random values in generated files unless the spec says so.
- Paths are built from `Path(__file__)`, never from the current working directory.
- Next.js: this version has breaking changes. Before writing Next.js code, read the relevant guide
  in `apps/web/node_modules/next/dist/docs/` (see `apps/web/AGENTS.md`).

## Commands (Windows paths; use `.venv/bin` on macOS/Linux)

Always use the project venv at `services/tutor/.venv`. Never `pip install` into the global Python:
the review checkpoint runs tests only through that venv.

```bash
cd services/tutor
python -m venv .venv                          # once
.venv/Scripts/pip install -e ".[dev]"         # once, and after pyproject.toml changes
.venv/Scripts/python -m pytest -q             # must pass before you finish
cd apps/web && npm run lint && npm run build  # only if you touched apps/web
```

## What you must not do

- Do not run `git commit`, `git push`, `git reset`, `git checkout -- <file>` or `git clean`.
  The owner submits your work to review with `python tools/task_runner.py submit <ID>`.
- Do not edit `TASKS.md` (not even the status board), `REQUIREMENTS.md`, `HUMAN-DECISIONS.md`, `QUALITY-AND-REVIEW.md`,
  `specs/`, `tools/` or `.github/`. They are owned by the owner and the reviewer.
- Do not commit secrets, `.env` files, licensed source documents or personal data.
- Do not change `tutor/grader.py`, `tutor/state_machine.py` or `tutor/tutor_voice.py` unless the
  spec says so.

## When you finish

End with a short report:

- Every test in the spec's test table, by name, and whether it exists and passes.
- Files created and changed.
- The exact test command you ran and its last line of output.
- Anything in the spec you could not do, and why.
