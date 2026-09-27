# Teach — Human Decisions

This file records the decisions that belong to the project owner, and the recommended default
for every decision still open. It follows the gates in `TASKS.md` and the product intent in
`REQUIREMENTS.md`.

How to read each item:

- **Decided** — the owner made this decision. Agents build to it.
- **Recommended** — a proposed default with the reasons and alternatives. It becomes a decision
  only when the owner writes "Confirmed" or a change next to it, with a date.
- **Open** — needs an answer or evidence that does not exist yet.

On 2026-09-27 the owner confirmed every recommendation in this file as written. The blanks that
remain are evidence still to come (source files, licence owner, calibrated threshold, audit results).

Copy each decided row into the decision log at the end, and into `TASKS.md` section 10.

---

## 1. Owner decisions (2026-09-27)

**D1. Content is reviewed by a grounded AI reviewer, not by a person, concept by concept.**
Decided. Teach will add courses that the owner cannot review personally, so review per concept by
a human does not scale. An AI reviewer checks every concept, rubric, task and answer key against
official sources and records its evidence. The owner, a CA, checks that the MVP works end to end
(section 3). Human experts audit samples; they do not review everything (section 2).

**D2. Teach is not limited to exams.** Decided. The long-term goal is to replace exams with a
verified record of what each student knows. Learning is personalised by the student's interests
and prior (graduation) knowledge. The system recommends the next new topic to learn, and existing
topics the student must strengthen. Exams become one possible goal among others (section 10).

**D3. Preserve the existing Phase 2 interfaces; do not install Git hooks.** Decided earlier.

**D4. Git identity is configured locally for this repository.** Decided earlier.

**D5. Code review checkpoint (2026-09-27).** Decided. Every task the coding agent completes stops
at a checkpoint. Claude, in a Claude Code session, reviews the change before it counts as done.
No new task starts while one waits for review. Built into `tools/task_runner.py`.
Refined the same day: Claude approves tasks that only change code. Tasks that change domain content
(concept maps, explanations, rubrics, calculators, answer keys, task templates, practice mapping,
eval expectations) are approved by the owner. GitHub Copilot may submit its own work to the
checkpoint and wait for the decision, but never approves (`specs/README.md`, "The loop").

**D6. Ollama models never review (2026-09-27).** Decided. Concepts must be right, so review of
code and content is done by Claude and by us, never by the Ollama models that write code and
drafts. This refines D1: the grounded reviewer is Claude (in the development session now, through
the Anthropic API when more courses are added), and a qualified professional signs off each
release. It replaces the earlier reviewer-model choice in section 2.

**D7. Students can flag errors (2026-09-27).** Decided. A student can mark any verdict, explanation,
citation or task answer as "I think this is wrong". When 10 different students flag the same item,
it opens to a community check inside Teach, where students who studied that concept are asked,
with a caution prompt, to confirm or reject it. If enough confirm it, the item goes to professional
review on the admin side; during development, it comes to us in the Claude Code session. Full
design in `QUALITY-AND-REVIEW.md` section 4; open thresholds in section 12 below.

**D8. Who writes which code (2026-09-27).** Decided. Claude writes the complex code itself:
architecture, contracts between modules, core algorithms, and code where determinism, security,
privacy or domain correctness is at stake. GitHub Copilot gets only easy tasks that follow an
existing pattern and are fully checked by their tests, each with a specific prompt (10 to 25 lines)
or a slim spec (about 5,000 characters or less). Claude never approves its own code; the owner
approves tasks Claude wrote. This saves Claude's tokens and saves rework rounds. It refines D5
(`specs/README.md`).

---

## 2. How grounded review works (the safeguards behind D1 and D6)

An AI reviewer can share the blind spots of the model that drafted the content. Because the ledger
is meant to replace exams, such errors would repeat for every student. These safeguards are part
of the decision; agents build them in `TASKS.md` T11 and T23.

1. **Official sources only, ranked.** For each course the content pack lists its sources in order
   of authority. Order: law or notified standard; the standard-setter's own
   pronouncements; the regulator's or professional body's study material; past papers with
   official answers. Coaching notes, videos and unreviewed scripts are never review evidence.
2. **Claim-level grounding.** The reviewer splits every item into single claims (each rubric item,
   explanation sentence, example, misconception, task answer step). Each claim needs a quote from a
   cited passage. Code confirms the quote appears word for word in that passage. A claim with no
   verbatim support fails.
3. **Claude reviews, a professional signs off (D6).** Claude judges every claim against the
   evidence; code refuses Ollama models as reviewers. A qualified professional signs off each
   release. Anything Claude marks unsure or wrong goes to the `needs_expert` queue.
4. **Answer keys stay deterministic.** Calculations are code. The reviewer checks each calculator
   against official worked illustrations with published solutions, which become the reference test
   cases. No model invents an answer key.
5. **Review statuses.** `draft` → `claude_reviewed` → `signed_off`. `needs_expert` blocks use.
   Strict mode also needs a recorded release sign-off. Every review is tied to the item's content
   hash, so editing an item sends it back through review.
6. **Sampled expert audit.** For each content release, a qualified expert audits a random sample
   plus every `needs_expert` item. For accounting and audit courses this can be the owner; for other
   courses, a subject expert engaged for that course.
7. **Student flags (D7).** Students flag doubts; ten flags open a community check; confirmed items
   go to professional review. Confirmed errors become regression cases for the reviewer.
8. **The reviewer is tested too.** Before the pipeline is trusted, Claude must catch deliberately
   planted errors (wrong paragraph, reversed rule, invented exception) in a test set.

| Setting | Decided | Alternatives and why not |
|---|---|---|
| Reviewer | Claude only (D6): in the Claude Code session during development; through the Anthropic API at scale. Never Ollama models. | Ollama reviewer models (earlier choice, withdrawn): cheaper, but the owner does not trust them to judge concepts. |
| Sample size per release | 10% of changed items, at least 10, plus all `needs_expert` items | Smaller samples miss systematic errors. Full review defeats D1. |
| Audit failure rule | Any substantive error found in the sample sends the whole release back through review, and the error becomes a test case | A percentage threshold such as 2% sounds precise but lets known errors ship. |
| Planted-error catch rate before a reviewer is trusted | At least 95% | Lower lets real errors through. |

Status: **Confirmed** by the owner, 2026-09-27; reviewer changed to Claude by D6 the same day.
Claude must pass the T23 planted-error test before its reviews count.

---

## 3. Owner acceptance of the MVP (replaces concept-by-concept CA review)

The owner verifies that the MVP behaves correctly, as a CA would judge it, without reviewing each
node.

- [ ] Run the demo script in `REQUIREMENTS.md` section 10 by voice, steps 1 to 8.
- [ ] Try five of your own explanations, including one confident wrong answer and one vague
      name-dropping answer. Check the verdicts are fair.
- [ ] Open ten random citations in the dashboard and confirm each supports what it is cited for.
- [ ] Complete each skill task once correctly and once with a deliberate error.
- [ ] Ask three questions outside the syllabus and confirm the tutor refuses to guess.
- [ ] Read the AI review report summary: pass rate, reviewer disagreements, `needs_expert` items.

Accepted by: ____________________  Date: __________  Notes: ______________________________

---

## 4. T00 baseline commit

**Decided: approve `638b803` and mark T00 done.** The commit holds 75 files. It does not contain
`.env`, grader captures, the virtual environment, `node_modules` or voice models. One flag:
`Pitch.pdf` is committed. That is fine while the repository is private; remove it from history
before the repository is ever made public if the pitch is confidential.

Status: **Confirmed** by the owner, 2026-09-27. T00 is marked done in `TASKS.md`.

---

## 5. Scope and sources (H1)

**5.1 Target attempt.** Decided: **CA Final, May 2027.** CA Final now runs only in May and
November. May 2027 leaves time to build and review. Practice questions can reuse RTPs, MTPs and past
papers from May 2026 and November 2026, each tagged with its own attempt, after the AI reviewer
confirms they still apply.
- November 2026: all RTPs and MTPs exist today, but the exam is weeks away, so the pack goes stale
  immediately. Choose only for a one-off demo.
- November 2027: too far; its RTPs and MTPs arrive late, which starves the practice feature.

Status: **Confirmed** by the owner, 2026-09-27.

**5.2 Chapters.** Decided: **one chapter, Ind AS 115**, plus only the Ind AS 37 paragraphs that
the onerous-contract node needs. The 42-node map already covers the chapter. Out of scope for this
pack: service concession arrangements, lease components under Ind AS 116, receivable impairment
detail under Ind AS 109, and first-time adoption.
- Adding Ind AS 37 as a full second chapter pairs well with an onerous-contract task, but adds 20 to
  30 nodes before anything is proven end to end.

Status: **Confirmed** by the owner, 2026-09-27.

**5.3 Sources.** Decided:
- Grading citations: the MCA-notified Ind AS 115 text as amended, with its stable paragraph numbers.
- Ind AS 37 paragraphs 66 to 69, including 68A on the cost of fulfilling a contract.
- Tutor explanations and official worked illustrations: the ICAI study material chapter on Ind AS 115
  for the target attempt.
- Practice and evaluation: RTPs, MTPs and past papers with official suggested answers.
- Amendments: whatever ICAI's applicability announcement for the target attempt includes. Check MCA
  amendment rules issued since the version of the text you hold.
- Never review evidence: coaching notes, videos, or the Audit audio scripts, which are unreviewed.

Files supplied (title, issuer, attempt, local path): __________________________________________

**5.4 Storage and licensing.** Decided:
- Keep ICAI files and any text extracted from them out of git. They live in
  `content/packs/*/sources/raw/`, which is gitignored, with a private backup. Commit only the source
  registry: titles, hashes and attempts. The corpus is rebuilt from the raw files.
- The MCA Ind AS text is published in the Official Gazette and is probably safe to commit. Confirm
  with counsel before the repository goes public.
- **Strategic item:** commercial use of ICAI material, including the Standards on Auditing, likely
  needs ICAI's permission. Every CA paper after the first depends on it. Start a licence or
  partnership conversation before any pilot with real students; it also fits the Phase 3 plan to
  work with institutions.
- Alternative: commit everything to a private repository. Simpler for several agents and machines,
  but the history keeps the material forever if the repository is ever made public.

Status: **Confirmed** by the owner, 2026-09-27.
Licence owner: __________________

**5.5 Ind AS 37 boundary.** Decided: include paragraphs 66 to 69 only and keep the onerous node at
Level 3. Alternative: drop the node for a pure Ind AS 115 pack; simpler, but loses one exam-relevant
concept and the onerous-task option. Exclude Ind AS 109 and Ind AS 116 cross-references.

Status: **Confirmed** by the owner, 2026-09-27.

---

## 6. Concept map (was H2: now AI review plus owner acceptance)

The AI reviewer checks all 42 nodes: accuracy, coverage, rubric, misconceptions, chapter and source
references. The owner does not review nodes one by one; the owner triages `needs_expert` items and
the sampled audit (section 2).

Coverage gaps already found in the current map, for the drafting agent to add as new nodes before AI
review:
- Non-refundable upfront fees (paragraphs B48 to B51). `REQUIREMENTS.md` FR-2 names it as a Step 1
  Level 3 example, but no node covers it.
- Customer's unexercised rights, or breakage (paragraphs B44 to B47).
- The practical expedient to recognise revenue at the amount the entity has a right to invoice
  (paragraph B16). Needed if a time-and-materials task is ever added.
- Customer acceptance clauses (paragraphs B83 to B86): mentioned once, not covered.

Rubric guidance for drafting: two or three rubric items per node, each sayable aloud in one sentence;
misconceptions written the way a student would say them.

AI review report reference: ____________________  `needs_expert` items triaged: __________

---

## 7. Skill and tasks (H3, Q5)

**7.1 Task set.** Decided: keep the four planned tasks, all set in **one fictional mid-size Indian
IT services company**:
1. a fixed-price implementation contract (cost-to-cost progress);
2. a change order mid-project (contract modification);
3. managed services with SLA penalties and bonuses (variable consideration);
4. a year-end invoice register (discrepancy hunt: premature revenue, duplicate billing, missing credit
   note, wrong-period recognition).

One company means less authoring and a coherent story, and it matches "revenue recognition for a
service-based company". The hunt draws on the owner's cut-off and revenue-quality experience.
- Time-and-materials billing: easy but shallow; a good warm-up later, not a replacement.
- Onerous contract: a good swap for variable consideration if a cost-side task is wanted; do not add
  a fifth task, since FR-12 caps the MVP at three or four.
- If time runs short, keep three: the hunt, cost-to-cost, and one judgement task.

Status: **Confirmed** by the owner, 2026-09-27.

**7.2 Ground truth for tasks under D1.** Task narratives and rubrics are drafted by agents and must
pass AI review. Answer keys are computed by calculator code. Each calculator is tested against
official worked illustrations with published solutions. The owner checks each task once during MVP
acceptance (section 3).

**7.3 Grading defaults.** Decided:
- About half the weight on numbers and half on judgement. The key treatment decision is a required
  item (for example, choosing cumulative catch-up in the modification task).
- Pass mark 0.75, with every required item met.
- Amounts in rupees, rounded to the nearest rupee; tolerance 0.5% or ₹1,000, whichever is larger;
  percentages to one decimal place; financial year 1 April to 31 March. State these in each brief.
- Hunt: four planted issues plus one or two clean rows that look suspicious. No penalty for false
  alarms in the MVP; they are logged.

Status: **Confirmed** by the owner, 2026-09-27.

**7.4 Unlock and remediation.** Decided:
- A skill unlocks only when all its tasks pass (FR-12).
- **When a task fails, do not downgrade the concept automatically.** Schedule a review and send the
  student straight to a teach-back on the mapped concept. The teach-back measures the concept; if it
  fails, its verdict downgrades the concept explicitly, with evidence. A pure arithmetic slip with
  correct reasoning gets a retry only. This keeps task evidence and concept evidence separate, which
  an employer-facing skill profile needs later. (This changes the T53 default; see `TASKS.md` Q3.)
- Alternative: downgrade to PARTIAL on failure. The dashboard reacts faster, but the two kinds of
  evidence get mixed.
- Three attempts before a task is parked.
- Tasks open only when their mapped concepts are verified; the demo keeps its override.

Status: **Confirmed** by the owner, 2026-09-27.

---

## 8. Evaluations and practice (H4)

Decided:
- The AI reviewer checks every expected verdict, citation and practice mapping against the sources.
  The owner spot-checks during MVP acceptance.
- Zero tolerance for a false VERIFIED; accept some false PARTIAL or NOT_MENTIONED. Over-crediting is
  the worst error for a record that replaces exams.
- At least two grader cases per Level 1 node, every acceptance-criterion case, and noisy or Hinglish
  speech cases.
- Practice items: keep only questions fully answerable from the pack; for multi-standard case
  questions keep just the Ind AS 115 part.

Status: **Confirmed** by the owner, 2026-09-27.

---

## 9. Retrieval threshold (H5)

Decided:
- Lean toward refusing: at most 5% false accepts (ideally none in the review set) and up to about 15%
  false refusals. FR-11 forbids uncited answers; a wrong refusal only costs one "outside the
  syllabus" reply.
- Calibration set: at least 30 in-scope, 30 out-of-scope and 20 near-miss questions (Ind AS 116, Ind
  AS 109, Ind AS 37 outside onerous contracts, old AS 7 and AS 9, GST on services).
- Recalibrate whenever the corpus changes.
- The owner approves the final number from the calibration report.

Status: **Confirmed** by the owner, 2026-09-27. The number itself is approved after calibration.

Approved `RETRIEVAL_MIN_CONFIDENCE`: __________  Date: __________

---

## 10. Long-term vision: personalised learning beyond exams (D2)

These shape the data model now, even though they are built after the MVP (`TASKS.md` milestone M10).

**Decided direction:**
- The mastery ledger becomes the student's verified record across every course. Exams, jobs and
  personal interests are all *goals*: sets of concepts at a required depth.
- A learner profile holds the student's graduation degree and subjects, interests, goals and
  preferred language.
- A placement diagnostic, informed by the graduation profile, finds what the student already knows,
  so no one is taught what they know.
- A recommender suggests the next new topic and the existing topics to strengthen. Its ranking is
  code, not a model decision: prerequisites met, gaps against the student's goals, interest match,
  revision due, and later demand signals. Every recommendation shows its reasons; a model may only
  phrase the explanation.
- Courses link to each other through prerequisite edges, so a topic in one course can require a
  concept from another.

**Decisions for later stages (confirmed 2026-09-27):**

| Decision | Decided | Alternatives and why not |
|---|---|---|
| Second course | Advanced Auditing: the audio scripts are already being converted, and it tests a second CA paper. Needs the ICAI permission in 5.4. | A graduation-level Financial Accounting bridge course: proves "beyond exams" and the graduation-profile idea, and needs no ICAI licence if built from public sources. A strong third course. |
| Learner profile data | Only degree, subjects, interests, goals and language, with consent, under India's DPDP Act 2023 | Collecting marks or institution details adds privacy risk without improving recommendations much at first. |
| How interests influence learning | Interests change the order and examples, never the verification standard | Letting interests lower the bar would make the record meaningless to employers. |
| Credential | A signed, portable ledger export the student owns and can share | Platform-only records trap students, and conflict with deletion rights when the platform must erase data. |

Status: **Confirmed** by the owner, 2026-09-27.

---

## 11. Product, privacy and release

**11.1 Authentication.** Decided: stay localhost-only until authentication exists. For the pilot,
use an OIDC-capable provider such as Supabase Auth, which can later link to the student's ICAI
registration number and to voice biometrics. A device token plus PIN is acceptable for the local
demo only, since a record that replaces exams needs real identity.

Status: **Confirmed** by the owner, 2026-09-27.
Implementer: ____________________  Required before: any pilot with real students.

**11.2 Student data and deletion.** Decided:
- The student can request deletion from their own logged-in session; an admin can too.
- Keep the ledger and transcripts while the account is active; they are the evidence.
- Ask for consent to use grader captures for research. Strip the student's identity from captures
  after 90 days and keep the de-identified transcript and verdict pairs as the evaluation and future
  training set. Without consent, delete captures after 90 days.
- Strip the student's identity from the off-syllabus log after 30 days.
- Never keep raw audio. Phase 2 voice biometrics would store voice embeddings under separate consent.
- Have a lawyer confirm the consent notice and deletion flow under the DPDP Act 2023 before a pilot.

Status: **Confirmed** by the owner, 2026-09-27.

**11.3 Prerequisite explanations.** Decided: keep `ALLOW_PREREQUISITE_EXPLANATIONS=0` for the MVP.
In the long term, prerequisites become proper nodes in a lower-level or bridge course, not uncited
background.

Status: **Confirmed** by the owner, 2026-09-27.

**11.4 Content release cadence.** Decided: one content release per CA attempt, started when ICAI
publishes the applicability announcement. Because reviews are tied to content hashes, only changed
items go through AI review again.

Status: **Confirmed** by the owner, 2026-09-27.

---

## 12. Student flag thresholds (D7)

The design is in `QUALITY-AND-REVIEW.md` section 4. The first number is the owner's; the rest are
recommendations to confirm.

| Setting | Value | Status |
|---|---|---|
| Flags that open a community check | 10 unique students | **Decided** (D7) |
| Confirmations that trigger professional review | 10 "It is wrong" votes from students other than the flaggers, and at least 60% of decisive votes | Recommended |
| Who can flag or vote | Only students who have worked on that concept; one flag and one vote per item | Recommended |
| When students are asked to vote | End of session only, never mid-lesson | Recommended |
| Community check closes without escalation | After 30 decisive votes below 60%, or 60 days | Recommended |
| While under professional review | Item keeps working; affected verdicts get a `disputed` ledger event; the reviewer can pause it | Recommended |
| Professional review target time | 7 days | Recommended |
| During development | Escalations come to the Claude Code session through `scripts/flags_report.py`; the owner decides | Recommended |

Status: Confirm / Change ______________________  Date: __________

---

## Decision log

| Question/task | Decision | Decider | Date | Evidence or follow-up |
|---|---|---|---|---|
| D1 Content review | Grounded AI review against official sources, with sampled expert audit; owner does MVP acceptance | Owner | 2026-09-27 | `REQUIREMENTS.md` FR-2, FR-12, NFR updated; `TASKS.md` T11, T23, rule 7 updated |
| D2 Scope of the product | Not limited to exams; personalised by interests and graduation knowledge; recommends next and weak topics | Owner | 2026-09-27 | `REQUIREMENTS.md` section 9; `TASKS.md` milestone M10 |
| D3 Phase 2 interfaces, Git hooks | Preserve interfaces; no hooks | Owner | earlier | — |
| D4 Git identity | Configured locally | Owner | earlier | — |
| T00 baseline commit | Approve `638b803`; T00 done | Owner | 2026-09-27 | `TASKS.md` status board |
| 2 AI review settings | Two reviewer models of different families (withdrawn by D6); 10% sample (min 10); any audit error returns the release; 95% planted-error catch rate | Owner | 2026-09-27 | — |
| D5 Code review checkpoint | Every coding-agent task stops at review; Claude approves code-only tasks, the owner approves domain-content tasks; Copilot may submit but never approve | Owner | 2026-09-27 | `tools/task_runner.py`; `QUALITY-AND-REVIEW.md` section 2 |
| D6 Reviewer | Claude and humans review code and content; Ollama models never review; professional sign-off per release | Owner | 2026-09-27 | `TASKS.md` T11, T23 |
| D7 Student flags | 10 unique flags open a community check; confirmed items go to professional review | Owner | 2026-09-27 | `TASKS.md` T85, T86, T66; thresholds in section 12 |
| D8 Who writes which code | Claude writes complex code; Copilot gets easy tasks with a specific prompt or slim spec; the owner approves Claude's code | Owner | 2026-09-27 | `specs/README.md`; `TASKS.md` section 1 |
| 5.1 Attempt (Q1) | CA Final May 2027; reuse May/Nov 2026 practice items after AI review | Owner | 2026-09-27 | `TASKS.md` T10 manifest |
| 5.2, 5.5 Scope | Ind AS 115 only, plus Ind AS 37 paras 66–69 for the onerous node; exclude Ind AS 109 and 116 | Owner | 2026-09-27 | — |
| 5.3, 5.4 Sources and storage (Q2) | Official sources listed in 5.3; ICAI material kept out of git; MCA text may be committed; ICAI licence conversation before any pilot | Owner | 2026-09-27 | Licence owner to be named |
| 7.1 Task set (Q5) | Four tasks in one fictional IT services company | Owner | 2026-09-27 | `TASKS.md` T50 |
| 7.3 Grading defaults | 50/50 numbers and judgement; pass 0.75 plus required items; ₹ tolerance 0.5% or ₹1,000; FY April–March | Owner | 2026-09-27 | `TASKS.md` T50 |
| 7.4 Task failure (Q3) | No automatic downgrade; schedule review and teach-back; arithmetic slips retry only; 3 attempts; mastery before tasks | Owner | 2026-09-27 | `TASKS.md` T53 |
| 8 Evaluations | Zero false VERIFIED; coverage rules in section 8 | Owner | 2026-09-27 | — |
| 9 Threshold approach | Lean toward refusing; calibration set rules; number approved after calibration | Owner | 2026-09-27 | H5 |
| 10 Long-term | Advanced Auditing as second course; minimal learner profile; interests change order not standard; signed portable ledger | Owner | 2026-09-27 | `TASKS.md` M10 |
| 11.1 Auth (Q4) | Localhost only until auth; OIDC provider such as Supabase Auth before any pilot | Owner | 2026-09-27 | Implementer to be named |
| 11.2 Retention | Consent-based research use; de-identify captures after 90 days, else delete; strip identity from off-syllabus log after 30 days; no raw audio; DPDP legal check | Owner | 2026-09-27 | `TASKS.md` T80 |
| 11.3, 11.4 | Prerequisite mode off for MVP; one content release per attempt | Owner | 2026-09-27 | — |
