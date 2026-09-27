# Code specs and prompts

Owner decision D8 splits the coding work. Claude writes the complex code itself: architecture,
contracts between modules, core algorithms, and code where determinism, security, privacy or domain
correctness is at stake. GitHub Copilot gets only easy tasks: a task that follows an existing
pattern, touches one or two modules, and is fully checked by its listed tests. If the instructions
must explain *how* (an algorithm or a design choice), not only *what*, Claude writes the code.

Each delegated task gets a specific instruction, never a long document:

- **Small task** (about 150 lines of code or less): a prompt of 10 to 25 lines in `specs/<ID>.md`.
- **Larger delegated task**: a slim spec of about 5,000 characters or less (see "Spec format").

Every task stops at the review checkpoint (D5). Claude reviews Copilot's work. Claude never approves
its own work: the owner approves the output of tasks Claude wrote, from a demo. Specs never contain
syllabus text or answer keys.

## Order

Do the tasks in this order. Each one must be approved before the next starts. "Owner approves"
marks tasks that change domain content, or that Claude wrote: Claude reviews them, but only the
owner approves them (D5, D8). Claude approves the others.

| Order | Spec | Task | Depends on | Coder | Owner approves |
|---|---|---|---|---|---|
| 1 | [T01](T01.md) | Baseline green and housekeeping | T00 (done) | Copilot | done |
| 2 | [T02](T02.md) | Shared contracts module | T01 | Copilot | done |
| 3 | [T10](T10.md) | Content pack layout and loader | T02 | Copilot | done |
| 4 | [T82](T82.md) | Voice verification mock endpoint | T01 | Copilot | no |
| 5 | [T11](T11.md) | Review gate | T10 | Copilot | done |
| 6 | [T20](T20.md) | Ingestion pipeline | T10 | Copilot | done |
| 7 | [T21](T21.md) | Source-ref resolver and passage API | T20 | Copilot | no |
| 8 | [T22](T22.md) | Retriever (node-linked + BM25) | T21 | Copilot | no |

T01 to T22 and T82 were specified before D8, so they keep their full specs and stay with Copilot.
From T23 on, the "Coder" column is set when the batch is written.

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

**Small task: prompt only.** Name the files to create or change, the exact signatures, the test
names with what each asserts, and the "done when" commands. 10 to 25 lines.

**Larger delegated task: slim spec**, about 5,000 characters or less:

- **Files**: what to create or change.
- **Code**: signatures, data shapes and regexes, which are binding. Add behaviour notes only where
  they are not obvious from the signature.
- **Tests**: test names and what each asserts.
- **Done when**: commands that must pass, including a clean-export test run.
- **Do not**: what is out of scope.
- **Prompt for Copilot**: the text to paste into Copilot Chat.

No goal or "read first" prose that repeats `TASKS.md`. When a task gets a spec, its section in
`TASKS.md` shrinks to a summary line and a link here.
