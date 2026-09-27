---
name: task-cycle
description: Run the Teach coding loop without the owner - hand the next specified task to Copilot CLI, review it, approve or reject, and continue until something needs the owner. Use with /loop, or when the owner says "run the task cycle", "keep going" or "do the next tasks".
---

# Task cycle

One iteration moves the board forward by one step. Under `/loop` it repeats until a stop condition.
Rules: `~/.claude/CLAUDE.md` (roles, review checkpoint), `specs/README.md` ("The loop"), and owner
decisions D5, D6 and D8 in `HUMAN-DECISIONS.md`.

## Each iteration

1. Run `python tools/task_runner.py status`.
2. **A task is in `review`:** review it now.
   - Build the packet: `python tools/task_runner.py review <ID>`.
   - Run the tests, then run them again in a clean `git archive HEAD` export in the scratchpad.
   - Read the logic files against `specs/<ID>.md`. Skim fixtures and generated files.
   - Small problems: fix them, commit the fix, then approve. Deviations from the spec are named in
     the approval note.
   - Real problems: `python tools/task_runner.py reject <ID> --reason "..."` with concrete, numbered
     fixes. Then go to step 3 for the same task.
   - Otherwise: `python tools/task_runner.py approve <ID> --by "Claude" --note "..."`.
3. **Nothing in review:** pick the first eligible task that has `specs/<ID>.md`.
   - Commit your own uncommitted edits first; `run` refuses a dirty tree.
   - Start it in the background: `python tools/task_runner.py run --task <ID>` with
     `run_in_background`. End the iteration; the finished run wakes you.
4. Log one line per iteration in your reply: task, action, result.

## Stop and report to the owner when

- a task changes domain content (concept map, rubrics, calculators, answer keys, task templates,
  practice mapping, eval expectations): the owner approves it (D5);
- a finished task has output the owner can see: show it (run the app or give a concrete example)
  with a short "try this" list;
- the same task was rejected twice, or `run` ends `blocked`;
- no eligible task has a spec: the next spec batch is Claude's design work, done in the main
  session, not in the loop;
- only human tasks (H1 to H6) remain eligible.

The report is one short summary: what landed (commits), what to try, and what needs the owner, with
clickable links to any file they must open. Then stop the loop.

## Never

- Approve a task Claude wrote itself, or a domain-content task.
- Push, add remotes or open pull requests.
- Let another model review (D6).
