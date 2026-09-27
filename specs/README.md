# Code specs for GitHub Copilot

Each file here defines the code for one task in `TASKS.md`: files, signatures, behaviour and
tests. Copilot writes the code from the spec. Claude and the owner review it at the checkpoint
(owner decision D5) and fix or reject it. Specs define code; they never contain syllabus text or
answer keys.

## Order

Do the tasks in this order. Each one must be approved before the next starts. "Owner approves"
marks tasks that change domain content: Claude reviews them, but only the owner approves them
(owner decision D5). Claude approves the others.

| Order | Spec | Task | Depends on | Owner approves |
|---|---|---|---|---|
| 1 | [T01](T01.md) | Baseline green and housekeeping | T00 (done) | done |
| 2 | [T02](T02.md) | Shared contracts module | T01 | done |
| 3 | [T10](T10.md) | Content pack layout and loader | T02 | yes (concept map moves; draft chapters) |
| 4 | [T82](T82.md) | Voice verification mock endpoint | T01 | no |
| 5 | [T11](T11.md) | Review gate | T10 | no |
| 6 | [T20](T20.md) | Ingestion pipeline | T10 | no (synthetic fixtures only) |
| 7 | [T21](T21.md) | Source-ref resolver and passage API | T20 | no |
| 8 | [T22](T22.md) | Retriever (node-linked + BM25) | T21 | no |

Specs for later tasks (T23, T30, T50 and on) are written after these are reviewed, so they build
on the code as it actually landed. When no eligible task has a spec, the loop stops and waits.

## The loop

Copilot and Claude coordinate through the status board and `tools/task_runner.py`. Nobody relays
messages.

```text
Copilot                                   Claude (Claude Code session)
-------                                   ----------------------------
implement specs/<ID>.md
submit <ID>  ---- status: review ---->    wait <ID> --for review wakes up
wait <ID> --for decision (blocks)         review: approve / small fix + approve / reject
             <--- status: done or todo -  (owner approves content tasks)
APPROVED -> NEXT <ID2>: start it
REJECTED -> fix feedback.md, submit again
```

1. **Start once.** In VS Code, open Copilot Chat in **Agent** mode with the strongest model you
   have. Paste the spec's "Prompt for Copilot" block, and add: "When done, follow 'When you
   finish' in the Copilot instructions and keep going until wait says NEXT none." Copilot reads
   `.github/copilot-instructions.md` automatically.
2. **Tell Claude.** In Claude Code, say "watch T10". Claude starts a background
   `wait T10 --for review` and schedules a one-time check at the estimated finish time, in case
   the watch is missed.
3. **Copilot finishes.** It runs `submit` (tests plus an `[awaiting review]` commit), then
   `wait <ID> --for decision`, which blocks.
4. **Claude reviews** as soon as the submit lands. Then Claude either:
   - approves, if the task does not change domain content;
   - fixes small problems, commits the fixes, and approves;
   - asks you to approve, if the task changes domain content; or
   - rejects with reasons (`reject <ID> --reason ...`), which are written to
     `.task-runs/<ID>/feedback.md`.
5. **Copilot continues.** Its `wait` prints `APPROVED ... NEXT <ID2>` or `REJECTED ...` and it acts
   on that. After each approval, Claude starts watching the next task.

**Limits.**
- Claude's watch and check live only in the open Claude Code session, and fire only while it is
  idle.
- Copilot's `wait` gives up after 30 minutes (`TIMEOUT`, exit 3). Copilot runs it again. If
  Copilot's chat ends instead, paste: "run `python tools/task_runner.py wait <ID> --for decision`
  and continue".
- You can still do any step by hand: `submit`, or tell Claude "review <ID>".

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
