# Teach — How We Keep Code and Content Right

Teach wants its mastery record to replace exams. That only works if students, employers and
institutions can trust two things: that the software behaves as specified, and that every concept,
rubric and answer is correct. This document explains how we check both, who has the final say,
and how students help catch mistakes. It is written for the team and for anyone evaluating Teach,
and section 6 condenses it for the pitch.

Decisions referenced here (D5, D6, D7) are recorded in `HUMAN-DECISIONS.md`. The build tasks are in
`TASKS.md`.

---

## 1. Four layers of assurance

| Layer | What it checks | Who has the final say |
|---|---|---|
| 1. Official sources and citations | Every verdict, explanation and task answer cites a passage from an official source. No citation, no answer. | The rules in code |
| 2. Review before release | Every concept, rubric, task and answer key is checked claim by claim against the official sources. | Claude reviews; a qualified professional signs off |
| 3. Student community check | Students flag what looks wrong; other students confirm or reject the flag. | Students raise it; they never change content themselves |
| 4. Professional review | Items the community confirms as wrong are examined and fixed. | A qualified professional |

Separately, all software written by coding agents passes a review checkpoint before it counts as
done (section 2).

---

## 2. Code review checkpoint (D5)

Coding agents write the software from `TASKS.md`, one task at a time: GitHub Copilot working from
the code specs in `specs/`, or the runner's agent on an Ollama model. Neither is trusted to judge
its own work. So every task stops at a checkpoint:

1. The code enters the checkpoint: the runner (`tools/task_runner.py run`) gives one task to its
   agent, or the owner submits Copilot's work (`task_runner.py submit <ID>`). Either way the tests
   run and the result is committed marked `[awaiting review]`. The task's status becomes `review`.
2. Nothing else runs while a task waits at the checkpoint.
3. Claude, working with the owner in a Claude Code session, reviews the change:
   `task_runner.py review <ID>` builds a packet with the diff, the test output, the agent's report
   and a checklist (scope, acceptance checks, invariants, domain correctness, test quality, no
   secrets or licensed text).
4. The reviewers close the checkpoint. Claude approves tasks that only change code; the owner
   approves tasks that change domain content, such as concept maps, rubrics or calculators:
   - `approve <ID>` marks the task done and unlocks the tasks that depend on it;
   - `reject <ID> --reason "..."` sends it back. The reason is added to the agent's next prompt;
     `--revert` also undoes the commit.

Ollama models never review code or content.

---

## 3. Content review before release (D6)

**Drafting** can be done by any model, including the Ollama coding model: new concept nodes,
rubrics, task narratives and model answers all start as `draft`.

**Review is done by Claude, never by Ollama models.** The review pipeline (`TASKS.md` T23) splits
every item into single claims, finds the passages each claim relies on in the official sources,
and checks that every quoted passage appears word for word in the source. Claude then judges each
claim: supported, contradicted, or not found.

- **During development**, Claude does this in the Claude Code session, with the owner, from the
  evidence packets the pipeline produces.
- **At scale**, when more courses are added, the same pipeline calls Claude through the Anthropic
  API. Code refuses to use an Ollama model as a reviewer.

**Answer keys are code.** Calculations are deterministic functions tested against the official
worked illustrations. No model invents an answer.

**A qualified professional signs off every release.** For accounting and audit courses this is the
owner, a CA. For other courses, it is a subject expert engaged for that course. Sign-off covers
every item Claude marked `needs_expert`, a random sample of the rest, and every item escalated by
students (section 4). Strict mode refuses to teach or grade anything not reviewed and signed off.

Item statuses: `draft` → `claude_reviewed` → `signed_off`, or `needs_expert` when Claude finds a
problem or is unsure. Every review is tied to the item's content hash, so any edit sends the item
back through review.

---

## 4. Student flags and community check (D7)

Students are the largest group of readers Teach will ever have. When something looks wrong to
them, we want to hear about it, without letting a loud group rewrite the syllabus.

### 4.1 The flow

```
Student sees something wrong
        │  "I think this is wrong" + a short reason
        ▼
Flag recorded (one per student per item)
        │  10 different students flag the same item
        ▼
Community check opens (visible to students who study that concept)
        │  students are asked, carefully, "is this wrong?" and must give a reason
        │  enough confirmations (recommended: 10 "wrong" votes and at least 60% of decisive votes)
        ▼
Professional review (admin queue)
        │
        ├── Error confirmed → content fixed and re-reviewed; affected students' records corrected
        │                      with new, explicit ledger events; flaggers told the outcome
        └── Not an error   → closed with a short explanation shown to flaggers and voters
```

### 4.2 Rules

- **What can be flagged:** a grading verdict, a tutor explanation, a citation, a task's feedback or
  answer, and a practice answer. Each flag points at the content item behind it (for example the
  concept node or task rubric item), so flags from different sessions add up.
- **Who can flag and vote:** only students who have worked on that concept. One flag and one vote
  per student per item. A reason is required.
- **"Be cautious" prompt:** voters are shown the item, its cited source passage, and the reasons
  given so far, and are asked to check the source before voting. Options: "It is wrong", "It is
  correct", "Not sure". "Not sure" does not count toward the decision.
- **Distraction-free timing:** students are asked to vote at the end of a session, never in the
  middle of a lesson, so the kiosk stays focused.
- **"Public" means inside Teach.** The community check is visible to other students on the
  platform, not on the open internet. It never shows who flagged or voted.
- **Students never change content or grades directly.** Only professional review does. While an
  item is under professional review, verdicts that used it are marked `disputed` in the ledger (a
  new event, nothing is edited); the reviewer can pause the item at once if the error is serious.
- **Abuse protection:** thresholds count unique students; the admin view shows voting patterns;
  a community decision never changes grading by itself.
- **Privacy:** flags and votes are part of the student's data and are deleted with it.

### 4.3 Thresholds

| Setting | Value | Status |
|---|---|---|
| Flags that open a community check | 10 unique students | Decided by the owner |
| Confirmations that trigger professional review | 10 "It is wrong" votes from students other than the flaggers, and at least 60% of decisive votes | Recommended; confirm in `HUMAN-DECISIONS.md` |
| Community check closes without escalation | after 30 decisive votes below 60%, or 60 days | Recommended |
| Professional review target time | 7 days | Recommended |

All thresholds are configuration, so they can change without code changes.

---

## 5. During app development

Before the admin screens exist, escalations come to us:

- Flags and votes are stored under `services/tutor/data/flags/`.
- `scripts/flags_report.py` lists everything that reached professional review, with the item, the
  source passage, the student reasons and the vote counts.
- We review that report together in the Claude Code session: Claude analyses each item against the
  official sources, and the owner decides. Decisions are recorded with the same tool the admin
  screen will use later, so nothing changes when the admin screen arrives.

---

## 6. For the pitch

**One line:** Teach grades only against official sources, every answer is reviewed before
release, and students and professionals keep it correct after release.

**Talking points:**

1. **Cite or refuse.** Every verdict and explanation points to the exact official paragraph. If the
   syllabus does not cover a question, Teach says so instead of guessing.
2. **Reviewed before any student sees it.** Every concept and answer is checked claim by claim
   against the source, and a qualified professional signs off each release. Answer keys are
   calculated by code, not written by AI.
3. **Students as a quality network.** Any student can flag a doubt. Ten flags open a community
   check; if the community confirms the problem, a professional reviews it, the content is fixed,
   and every affected record is corrected transparently.
4. **Trustworthy for employers.** The record is append-only: corrections are added, never hidden.
   Every mastery claim traces back to the student's own words and the source it was judged against.

---

## 7. Where each piece is built

| Piece | `TASKS.md` |
|---|---|
| Code review checkpoint | `tools/task_runner.py` (done); section 1 "Automated runner" |
| Review statuses and release sign-off | T11 |
| Claude review pipeline (no Ollama reviewers) | T23 |
| Student flags and community check | T85 |
| Professional review queue and development report | T86 |
| Flag and vote screens in the kiosk | T66 |
