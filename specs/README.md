# Code specs for GitHub Copilot

Each file here defines the code for one task in `TASKS.md`: files, signatures, behaviour and
tests. Copilot writes the code from the spec. Claude and the owner review it at the checkpoint
(owner decision D5) and fix or reject it. Specs define code; they never contain syllabus text or
answer keys.

## Order

Do the tasks in this order. Each one must be approved before the next starts.

| Order | Spec | Task | Depends on |
|---|---|---|---|
| 1 | [T01](T01.md) | Baseline green and housekeeping | T00 (done) |
| 2 | [T02](T02.md) | Shared contracts module | T01 |
| 3 | [T10](T10.md) | Content pack layout and loader | T02 |
| 4 | [T82](T82.md) | Voice verification mock endpoint | T01 |
| 5 | [T11](T11.md) | Review gate | T10 |
| 6 | [T20](T20.md) | Ingestion pipeline | T10 |
| 7 | [T21](T21.md) | Source-ref resolver and passage API | T20 |
| 8 | [T22](T22.md) | Retriever (node-linked + BM25) | T21 |

Specs for later tasks (T23, T30, T50 and on) are written after these are reviewed, so they build
on the code as it actually landed.

## Loop for one task

1. Check what is next:

   ```bash
   python tools/task_runner.py status
   ```

2. In VS Code, open Copilot Chat in **Agent** mode. Choose the strongest model you have. Paste the
   "Prompt for Copilot" block from the spec. Copilot reads `.github/copilot-instructions.md`
   automatically.
3. Let Copilot finish. It must end with the test command it ran and the result. If tests fail,
   ask it to fix them.
4. Submit the work to the checkpoint. This runs the tests, commits the work as
   `[awaiting review]` and sets the task to `review`:

   ```bash
   python tools/task_runner.py submit T01 --by "Copilot (<model name>)" --notes "<paste Copilot's final report>"
   ```

5. In Claude Code, say **"review T01"**. Claude builds the review packet, checks the code against
   the spec and the rules, and then either:
   - fixes small problems directly and approves with you, or
   - rejects with reasons: `python tools/task_runner.py reject T01 --reason "..."`. The reasons
     are saved to `.task-runs/T01/feedback.md`. Go back to step 2 and add: "Also fix the review
     feedback in `.task-runs/T01/feedback.md`."

## Before you start

- Commit or stash your own changes first. `submit` commits everything in the working tree.
- Pause OneDrive sync while Copilot works. OneDrive has already overwritten files in this repo
  once.

## Spec format

Every spec has the same parts:

- **Goal**: one paragraph.
- **Read first**: files to read before writing code.
- **Files**: what to create or change.
- **Code**: signatures and behaviour. Signatures are binding; bodies are for Copilot.
- **Tests**: test files, test names and what each asserts.
- **Done when**: commands that must pass.
- **Do not**: what is out of scope.
- **Prompt for Copilot**: the text to paste into Copilot Chat.
