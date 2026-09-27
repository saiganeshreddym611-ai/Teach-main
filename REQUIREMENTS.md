# Teach — Requirements Prompt for Code Agents

Source: `Pitch.pdf` (Voice-AI Educational Reform Startup Pitch, 2026-09-17), distilled into
requirements and the exam-tutor product brief. Read this before changing product behaviour. When
code and this document disagree, raise it; do not silently pick one. The product brief extends the
hackathon MVP to include syllabus-grounded citations and one task-based skill; it does not replace
the code-owned learning loop or mastery ledger described below.

Owner decisions of 2026-09-27 (recorded in `HUMAN-DECISIONS.md`): **D1** content is reviewed by a
grounded AI reviewer against official sources, with sampled expert audits, instead of a CA reviewing
each concept; **D2** Teach is not limited to exams, and learning is personalised by the student's
interests and graduation knowledge (section 9); **D5** every task written by a coding agent stops at
a review checkpoint; **D6** Ollama models never review code or content, Claude and qualified people
do; **D7** students can flag errors, which reach professional review through a community check
(FR-14). How these fit together: `QUALITY-AND-REVIEW.md`.

## 1. Vision (one paragraph)

A distraction-free, voice-first, conversational learning system grounded in one exam's syllabus.
The student explains what they know; an AI tutor checks each claim against reviewed syllabus
material, identifies errors and omitted concepts, teaches Socratically, verifies understanding
through teach-back, and records every verified concept in an immutable **mastery ledger** with
traceable evidence. After concept mastery, the student completes realistic company tasks to unlock
job-level skills. First domain: CA Final, Financial Reporting, Ind AS 115 (Revenue from Contracts
with Customers). The architecture must allow another exam or attempt to be loaded by replacing its
content, without retraining a model. Longer term, Teach is not limited to exams: the ledger replaces
exams as the verified record of what the student knows, and the system recommends what to learn
next based on the student's interests, graduation knowledge and goals (section 9).

## 2. Problems being solved

1. **Distraction.** Smart devices are built for media consumption; deep study on them is hard.
2. **Flawed testing.** Exams sample ~10% of a syllabus to judge the whole student; arbitrary
   pass/fail, high anxiety, and years of work can go in vain on one bad day.
3. **Passive learning.** Lectures give no real-time feedback; students discover gaps only after
   failing.

## 3. Solution layers

| Layer | Component | Function | MVP? |
|---|---|---|---|
| Hardware | Dedicated locked-down device | Zero-distraction execution boundary | No (Phase 2) |
| Software | Socratic voice tutor | Adaptive teaching + teach-back verification | **Yes** |
| Credentialing | Continuous knowledge ledger | Real-time matrix of mastered vs pending concepts | **Yes** |
| Grounding | Reviewed concept map + syllabus retrieval | Bound claims, explanations and task grading to citable exam material | **Yes** |
| Skills | Authored company-task templates | Apply concepts to realistic work; unlock a skill when all its tasks are cleared | **Yes** |
| Integrity | Voice biometrics + fraud guard | Proves the ledger reflects the unassisted student | Mock only |
| Macro engine | Supply/demand data pipeline | Workforce capacity and educator planning | No (Phase 3) |

## 4. Core learning loop (the Feynman cycle)

Every session runs this loop. It is the product.

1. **Baseline diagnostic.** System: "Tell me everything you know about Ind AS 115." Student speaks
   freely (about 60 seconds, but unbounded).
2. **Syllabus mapping.** System maps the transcript onto the official curriculum, marks every
   accurately described concept, and identifies gaps and errors.
3. **Interactive instruction.** System teaches the missing concept by voice, step by step,
   Socratically, in under 90 seconds per turn.
4. **Teach-back verification.** System: "Now explain that back to me in your own words with an
   example." Student explains; system validates.
5. **Ledger update.** Verified concept is recorded in the student's immutable profile. Loop
   returns to step 3 with the next missing concept.

## 5. Functional requirements (MVP)

### FR-1 Voice-to-voice interface
- Full-screen kiosk UI, no navigation, one talk affordance, audio waveform visualiser.
- Speech-to-text for student input; text-to-speech for tutor output. Browser APIs are acceptable
  for the MVP; hosted STT/TTS (Deepgram, ElevenLabs) or local engines may replace them.
- Tutor speech must start before the full response has been generated (stream sentence by
  sentence). Target: first spoken sentence within a few seconds of the student finishing.

### FR-2 Hierarchical knowledge tree (not a linear script)
The curriculum is a three-level taxonomy so one flow serves beginners and advanced finalists.

```
Level 1: Macro structure     (the 5-step revenue model)
Level 2: Micro criteria      (specific technical parameters for each step)
Level 3: Advanced exceptions (contract modifications, variable consideration, warranties, ...)
```

Example for Step 1 (identify the contract):

| Level | Coverage |
|---|---|
| L1 | Says Step 1 is "identify the contract with the customer". |
| L2 | Details the 5 criteria: approval/commitment, identified rights, payment terms, commercial substance, collectability. |
| L3 | Explains contract modifications (prospective vs cumulative catch-up), combination of contracts, non-refundable upfront fees. |

Each node needs: id, level, parent, title, a grading rubric (what must be said to count),
known misconceptions, a canonical explanation, an example, and source references to the exact
reviewed material passage. Atomic nodes make teach-back gap detection, mastery tracking and task
mapping consistent. An LLM may draft a map. Before it is used for grading or teaching, every node
must pass grounded review by Claude for accuracy and coverage against the official sources, and a
qualified professional signs off each release (D1, D6; safeguards in `HUMAN-DECISIONS.md` section 2).
Ollama models may draft content but never review it.

### FR-3 Grading (extract and map)
- Map every concept the student mentions to tree nodes.
- Status per node: `VERIFIED` (all rubric items evidenced accurately), `PARTIAL`, `GAP`
  (mentioned but wrong, or asked and not known), `NOT_MENTIONED`.
- Merely naming a topic is not evidence; the student must state the content.
- Grading must be strict, repeatable (same transcript, same verdicts) and produce structured
  output, never free text.
- Every verdict carries a confidence score, the evidence it rests on, and a citation to the exact
  source passage supporting the judgment. Do not grade a claim against general model knowledge.

### FR-4 Deepest missing node selection
- After grading, pick the highest-priority unverified node, walking Level 1 first, then Level 2,
  then Level 3. This selection is deterministic code, not an LLM decision.
- Beginner who covers L1 partially and misses Steps 3–5 gets a macro drill ("You identified Steps
  1 and 2. Now let's look at Step 3...").
- Advanced finalist who covers all of L1 and parts of L2 gets a micro / L3 drill ("Great baseline.
  What happens if a contract modification occurs halfway?").

### FR-5 Adaptive tutor voice
- Shallow knowledge: simple, encouraging, core frameworks only.
- Deep knowledge: acknowledge fundamentals immediately, skip introductions, challenge with edge
  cases, exemptions and exam-level scenarios.
- One concept per turn, at most ~120 words, ends with a question. The tutor never grades and
  never writes to the ledger.
- Be Socratic first: for an identified gap, ask a probing question before revealing the answer.
  If the student remains stuck, explain the rule with its source citation.
- Keep answers within retrieved, in-scope syllabus material. Clearly label any explicitly enabled
  prerequisite explanation as beyond the current scope.

### FR-6 Teach-back
- After instruction, the tutor asks the student to explain the concept back with an example.
- The grader scores the teach-back against the target node's rubric.
- Pass: ledger records the node as verified. Fail: re-teach, bounded retries, then park the node as
  a gap and move on.
- Corrections and teach-back grading cite the exact reviewed source passage used.

### FR-7 Mastery ledger
- Append-only events: `{student_id, node_id, status, confidence, evidence_turn_id, timestamp}`.
- Current mastery is a projection over events; a verified node is never silently downgraded.
- Every mastery claim must be traceable to the exact transcript turn that earned it.
- Reference shape from the pitch:

```json
{
  "student_id": "ca_final_001",
  "subject": "Financial Reporting",
  "standard": "Ind AS 115",
  "nodes": [
    {"concept_id": "step_1_contract_identification", "status": "MASTERED", "confidence_score": 0.92, "last_verified": "2026-09-15T12:00:00Z"},
    {"concept_id": "step_4_transaction_price_allocation", "status": "GAP_IDENTIFIED", "confidence_score": 0.45, "last_verified": "2026-09-15T12:02:00Z"}
  ]
}
```

### FR-8 Mastery dashboard
- Visual grid of the tree: L1 rows, L2/L3 chips, colour-coded verified / partial / gap / pending.
- Updates live as the session runs.

### FR-9 Voice verification (mock)
- Interface `verify(audio) -> {match, score}`. MVP returns a fixed match. Real acoustic
  fingerprinting is Phase 2. Keep it a swappable module.

### FR-10 Syllabus content and retrieval
- MVP content covers CA Final Financial Reporting, Ind AS 115, in one or two chapters. Ingest the
  applicable study material, RTPs, MTPs, past papers and amendments for the selected attempt.
- Split material into searchable chunks with stable source references and paper, chapter, section
  and attempt/version metadata. Every answer, correction and grading decision must cite the exact
  supporting passage; a citation must resolve back to the source document and passage.
- Retrieval is limited to the selected syllabus corpus and the reviewed concept map. When material
  for a new attempt is released, update or swap the versioned documents and index without code
  changes or model retraining.
- Use a compact retrieval index. Prefer node-linked retrieval for mapped concepts; similarity
  search can support relevant passage lookup and syllabus question handling.

### FR-11 Syllabus boundary and confidence guard
- Tutor answers, grading decisions and Skills tasks must be supported by retrieved syllabus
  material and mapped concepts. Do not use uncited general knowledge to fill gaps.
- When retrieval confidence is below a configured threshold or no supporting passage is found,
  say that the question is outside the available syllabus material rather than guessing.
- An optional softer mode may briefly cover a prerequisite from an earlier level, explicitly
  labelled as beyond scope. It must not change syllabus grading or mastery.

### FR-12 Skills Acquired: task-based skill unlocking
- A **skill** is a job-level capability (for example, revenue recognition for a service-based
  company) made up of one or more authored tasks. Each task maps to reviewed concepts in the
  concept map and together the tasks cover routine treatments, anomalies and exception cases.
- MVP includes one Ind AS 115-related skill with three or four tasks, including a discrepancy hunt.
  Use realistic fictional companies modelled on real-world patterns; public annual-report
  disclosures may be used for reading and interpretation when appropriately sourced.
- Grade task answers against an authored model answer and rubric using the claim-checking engine.
  Return partial credit and citations; failed tasks route the student back to teach-back on the
  underlying concept.
- A skill unlocks only when every task in its set is cleared. Show skill state and remaining tasks.
- Tasks originate from authored case templates. Solutions are computed by deterministic code,
  tested against official worked illustrations, and pass grounded review by Claude against
  official sources with professional sign-off (D1, D6). AI may vary names, amounts and dates only
  within template constraints. Calculations must be deterministic code or
  checked against the answer key; the AI must never invent a solution or answer key.
- The MVP revenue-recognition skill should cover a representative mix such as fixed-price
  cost-to-cost recognition, time-and-materials billing, a contract modification, variable
  consideration, contract asset/liability cut-off, an onerous contract, and a discrepancy hunt
  for errors such as premature revenue, duplicate billing, missing credit notes or wrong-period
  recognition. Select three or four tasks that provide meaningful coverage, including the hunt.

### FR-13 Mastery, revision and practice
- Maintain concept mastery from teach-back results and task performance without weakening the
  evidence trail in the append-only ledger.
- Resurface weak concepts through spaced repetition. Generate exam-style practice from applicable
  RTPs, MTPs and past papers, retaining exact source citations.
- The dashboard shows concept mastery by chapter and skills as locked, in progress or unlocked,
  including tasks remaining.

### FR-14 Student flags, community check and professional review (D7)
- A student can mark a grading verdict, tutor explanation, citation, task feedback or practice
  answer as "I think this is wrong", with a short reason. Each flag points at the content item
  behind it, so flags from different sessions add up. One flag per student per item.
- When 10 different students flag the same item, it enters a community check inside Teach
  (never on the open internet, never showing identities). Students who have worked on that concept
  are asked, at the end of a session and with a caution prompt showing the cited source, whether it
  is wrong. "Not sure" does not count.
- When enough students confirm it (thresholds in `HUMAN-DECISIONS.md` section 12), the item goes to
  professional review on the admin side. During development it comes to the Claude Code session.
- Students never change content or grades. Only professional review does. While an item is under
  professional review, verdicts that used it receive a `disputed` ledger event. A confirmed error
  is fixed through normal review, affected ledger entries receive explicit corrective events, and
  flaggers see the outcome. A rejected flag is closed with a short explanation.
- All thresholds are configuration. Flags and votes are student data and are deleted with it.

## 6. Non-functional requirements

- **Flow is owned by code.** A state machine (DIAGNOSTIC → INSTRUCT ⇄ TEACH_BACK → COMPLETE)
  decides what happens; the LLM is a component called with a directive. The LLM never chooses
  the phase or the next node.
- **Auditability.** Log every grader call (input, rubric, output). These logs are the eval set.
- **Determinism where it matters.** Grader runs at temperature 0 with structured output; the tutor
  voice may be creative.
- **Accuracy and review.** Correctness of teaching and grading takes priority over latency.
  Concept maps, task templates, rubrics and solutions require grounded review against official
  sources before use: claim-level evidence judged by Claude, verbatim quote checks in code, and
  sign-off by a qualified professional for every release (D1, D6). Ollama models never review.
- **Review checkpoint for code.** Code written by coding agents counts as done only after Claude
  and the owner review it at the runner's checkpoint (D5).
- **Community correction.** Students can flag errors; confirmed flags reach professional review
  (FR-14, D7).
- **Traceability.** Every verdict is auditable to its retrieved source passage and the student's
  evidence; every task result is traceable to its authored case, rubric and verified solution.
- **Latency and efficiency.** Stream responses; target grade + first spoken sentence within a few
  seconds. Keep the syllabus index compact and prompts focused to control model latency and cost.
- **Distraction-free.** No navigation, notifications, links or secondary content on screen.
- **Portability.** Browser STT/TTS today; server-side streaming audio and on-device kiosk later
  without rewriting the orchestrator.
- **Maintainability.** A new exam attempt's content can be versioned and swapped without code or
  model changes. Keep exam content, concept maps, task templates and application logic separable.
- **Privacy.** Store voice and performance data securely and provide a way to delete a student's
  data. Retain only the evidence required for the student's ledger and consented product operation.

## 7. Out of scope for the MVP

- Locked-down device firmware / Android kiosk launcher.
- Real voice biometrics, speech-dynamics script detection, hardware air-gap.
- Full CA curriculum or multiple exams; only CA Final Financial Reporting, Ind AS 115 (one or two
  chapters), and one related skill with three or four tasks.
- Employer skill-matrix API, certified skill profiles for job matching.
- Macro workforce engine (skill analytics dashboard, enrollment corridors, educator balancing).
- Professional-ethics scenario module (Socratic dilemmas for attitude and values).
- Distilling the grading task into a fine-tuned model or deploying grading on-device; version 1
  uses a general-purpose model with retrieval and no custom training.
- Persistent database (in-memory store is acceptable if the interface is swappable), unless needed
  to securely support the MVP's student data and deletion requirements.

## 8. Roadmap (for context, not for MVP work)

| Phase | Target | Deliverable |
|---|---|---|
| 1 Hackathon MVP | CA Final FR, Ind AS 115 (one or two chapters), one skill | Text teach-back against source material; retrieval with citations; reviewed concept map and gap-finding; three or four authored skill tasks including discrepancy hunt; then voice, mastery and skill dashboard |
| 2 Product + hardware | More papers and exams; custom Android/Linux launcher on low-cost hardware | Versioned content ingestion; larger task/skill library; on-device speech, flashcards and quizzes; granular skill-mapping APIs; real voice biometrics |
| 3 Reform + policy | Government bodies, higher-education institutions | Certified skill-matrix profiles replace exams; workforce capacity planning (±5% buffer corridors) |

Version 1 uses a capable general-purpose LLM through an API, with retrieval over syllabus
documents; it does not use a custom-trained model. The deployment may be hybrid: speech-to-text,
flashcards and simple quizzes on device, with claim-checking, tutoring and task grading in the
cloud. Grading-model distillation using reviewed examples is a later cost and on-device
optimization; the syllabus remains in retrieval.

Strategic alignment: competency-based education (NEP 2020), democratised 1-on-1 mentorship, and
direct hiring on granular proof of capability ("mastered 95% of complex financial instruments").

## 9. Job-scoped learning and demand-aware guidance (Phase 2-3 goal)

Stated in the founder's brief inside the pitch but absent from its structured sections. Treat it as
product direction that the MVP data model must not block.

- **Study only what the job needs.** A *job profile* is a set of tree nodes with a minimum depth
  for each. A student targeting a job studies that set, not the whole syllabus.
- **Adjacent fields to basic or integration depth only.** Areas outside the core of the job are
  required to Level 1, or to the specific nodes needed to work with the core, never to full depth.
- **Depth maps to role tier.** Deeper verified coverage (more Level 2 and Level 3 nodes) qualifies
  for higher-paid roles in the same field. The system shows the student which additional nodes
  unlock the next tier, so the incentive to go deeper is explicit and honest.
- **Multi-field jobs.** A job profile can span fields (for example Financial Reporting plus Audit).
  The ledger records every field, so eligibility is a set comparison, not a score.
- **Honest demand guidance.** Using workforce data (the Phase 3 macro engine), the system tells
  students plainly which sectors have demand, which are saturated, and what depth pays. Guidance
  must show the data behind it and must never hide oversupply to keep a student enrolled.

### Personalised learning beyond exams (owner decision D2)

- **Exams are one goal among several.** A goal is a set of nodes with a minimum depth: an exam
  attempt, a job profile, or a topic the student is interested in. The ledger is the same for all.
- **Learner profile.** Graduation degree and subjects, interests, goals and preferred language,
  collected with consent and kept minimal.
- **Start from what the student knows.** A placement diagnostic, informed by the graduation
  profile, verifies existing knowledge so the student is never taught what they already know.
- **Recommend the next topic and the topics to strengthen.** Ranking is deterministic code over the
  ledger, the course graph and the profile: prerequisites met, gaps against goals, interest match,
  revision due, and later demand signals. Every recommendation shows its reasons. A model may phrase
  the explanation but never chooses the topic.
- **Courses connect.** Nodes can require nodes in other courses through prerequisite edges, so a
  bridge from graduation-level knowledge to professional topics is part of the same graph.
- **Interests change the path, never the standard.** Order and examples adapt; verification rules
  do not.

Implications for the data model (cheap to respect now):

- Keep node `level` as the depth tier. Add `job_profiles/*.json` later:
  `{job_id, title, sector, required: [{node_id, min_status}], adjacent: [{node_id, min_status}], pay_band}`.
- The ledger does not change. "Qualified for job X" is a projection: every required node is
  `VERIFIED`.
- The node selector gains an optional job-profile filter: walk only nodes in the profile, core
  before adjacent.
- Demand signals arrive as a read-only feed; guidance consumes them, never the grader.

Not in the MVP. One seeded job profile is acceptable for a demo if it costs nothing.

## 10. Acceptance criteria (demo script)

1. Start a session; the student explains revenue recognition by voice or text, omitting allocation
   and claiming revenue is recognized on invoicing.
2. The grader separates the explanation into claims, identifies the omitted allocation concept
   and the invoicing misconception, and cites the exact source passage for each verdict. The
   dashboard and ledger retain the evidence and source references.
3. For the gap, the tutor asks a Socratic follow-up before explaining. If the student remains
   stuck, it explains the rule with a citation and asks for a teach-back.
4. A confident wrong teach-back (for example, allocating on cost) stays unverified; the tutor
   corrects the specific misconception with a citation and applies bounded retries.
5. The student completes one authored task, makes an error, and receives a rubric-based,
   partially creditable correction with citations; a failed task routes back to its mapped concept.
6. After all tasks for the skill are cleared, the skill unlocks. The dashboard shows its state and
   remaining tasks until that point.
7. Same transcript graded three times yields identical statuses. Task calculations and generated
   case variants match the verified answer key.
8. A question without sufficiently confident in-syllabus evidence is identified as outside the
   available syllabus material instead of receiving an uncited general-knowledge answer.
9. Ten students flag the same explanation; it enters the community check; enough students confirm
   it; it appears in the professional review queue (or the development report). The reviewer
   confirms the error, and affected ledger entries receive corrective events without anything
   being deleted.

## 11. Domain and delivery roles

- **Owner and domain expert (Swetha):** selects the official sources; sets grading policy;
  accepts the MVP end to end as a CA; audits sampled and `needs_expert` items for accounting and
  audit courses; signs off releases; decides escalated student flags; owns the pitch.
  Concept-by-concept checking is done by Claude with evidence (D1, D6). Her FDD
  experience in revenue quality, cut-off testing and anomaly detection informs the task and
  discrepancy-hunt design.
- **Claude (reviewer):** reviews every coding-agent change at the checkpoint and checks content
  claim by claim against official sources, in the Claude Code session during development and
  through the Anthropic API at scale (D5, D6).
- **Subject experts for other courses:** sign off releases and decide escalated flags for courses
  outside the owner's field.
- **Developer (if on a team):** implements application plumbing, retrieval and versioned content
  pipeline, voice integration, task calculation safeguards and UI. Solo or team delivery remains
  undecided.

## 12. Constraints and open questions from the pitch

- Employers must be able to trust that the ledger reflects the unassisted student (motivates the
  integrity layer).
- Hiring is not only knowledge; attitude and ethics matter. Proposed answer: ethics scenarios in the
  same voice loop. Unresolved; not in MVP.
- Fairness across learner levels: the same opening prompt must work for a beginner and a finalist
  with several attempts behind them (motivates the three-level tree and adaptive tone).
- Review must scale beyond the owner's field: later courses will have no reviewer on the team, so
  content quality rests on Claude's grounded review, professional sign-off and student flags
  (D1, D6, D7).

## 13. Repository context

This repository implements the original tutor-loop baseline: `curriculum/ind_as_115.json`
(three-level tree), `services/tutor/` (FastAPI orchestrator, state machine, grader, tutor voice,
ledger, TTS) and `apps/web/` (Next.js kiosk). The syllabus ingestion and retrieval, cited claim
checking and task-based skill flow in this requirements document extend that baseline; do not
assume they are already implemented. See `README.md` for how to run the current app and which
models and voices are configured. Use this document to judge whether a change serves the product;
use `README.md` and the code for how things are built.
