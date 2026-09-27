# Teach — Task Plan for Code Agents

This file breaks `REQUIREMENTS.md` into tasks that coding agents can pick up, one at a time, over
many sessions. It is a plan, not a spec: `REQUIREMENTS.md` says **what** the product must do,
`README.md` and the code say **how** it is built today, and this file says **in what order to
change it and how to prove each change works**.

Planned on 2026-09-27 against the baseline in this repository (hackathon MVP: state machine,
grader, tutor voice, ledger, kiosk). Nothing in this plan has been implemented yet.

---

## 1. How to use this file

1. Read `REQUIREMENTS.md`, `README.md`, section 2 (rules) and section 3 (contracts) of this file
   before you start any task.
2. Pick a task from the **status board** (section 4) whose status is `todo` and whose
   dependencies are all `done`. Prefer the lowest wave number (section 7).
3. Claim it: set its status to `in progress (<agent name>, <date>)`. The status board is the only
   place status lives. Do not add status lines inside task sections.
4. Work on a branch or worktree named `task/<ID>-<short-slug>`, for example
   `task/T21-source-ref-resolver`. One task per branch.
5. When the acceptance checks pass, set the status to `review` and list what you ran and the
   results in your commit message. A human or a reviewer agent moves it to `done (<commit>)`.
6. If you are blocked, set `blocked (<reason>)` and add a row to the Open Questions log
   (section 10). Then pick another task.
7. If you find that code and `REQUIREMENTS.md` disagree, do not silently pick one. Add a row to
   the Open Questions log and follow section 9 if the disagreement is already listed there.

### Definition of done (every task)

- Every acceptance check in the task passes, and you ran it, not assumed it.
- `pytest` is green in `services/tutor`. New behaviour has new tests.
- `MOCK_LLM=1` still runs a full session end to end. Every new LLM-backed component ships a Mock
  implementation and is selected through the existing factory pattern in `tutor/llm.py`.
- If you touched `apps/web`, `npm run lint` and `npm run build` pass.
- If you changed any prompt text, the grader output schema, or how the concept map is serialised
  into a prompt, you bumped `PROMPT_VERSION` and re-ran the grader evals (or wrote in the commit
  message that no model was available and the evals were not run).
- New environment variables are added to `services/tutor/.env.example` and the README table.
- No review status was set by hand. Only the review pipeline (T23) or a recorded human sign-off
  sets it (see rule 7 below).
- The task passed the review checkpoint: Claude reviewed it and ran `task_runner.py approve`; for
  tasks that change domain content, the owner approved it (owner decision D5). A coding agent never
  approves its own work.
- Commit message starts with the task ID, for example `T21: resolve node source_refs to passages`.
- Never push to a remote or open a PR unless a human asked for it.

### Commands

```bash
# backend (Windows paths; use .venv/bin on macOS/Linux)
cd services/tutor
.venv/Scripts/python -m pytest
MOCK_LLM=1 .venv/Scripts/python -m uvicorn tutor.main:app --port 8000
.venv/Scripts/python tests/evals/grader/run_evals.py --repeat 3
.venv/Scripts/python tests/evals/tutor/bench_tutor.py

# frontend
cd apps/web
npm run lint && npm run build
npm run dev
```

Before writing any Next.js code, follow `apps/web/AGENTS.md`: this Next.js version has breaking
changes, so read the relevant guide in `apps/web/node_modules/next/dist/docs/` first.

### Automated runner

`tools/task_runner.py` gives the next eligible task to a coding agent (Claude Code in headless
mode, pointed at the local Ollama model, by default), runs pytest, commits the result as
`[awaiting review]`, and stops at the **review checkpoint** (D5). No other task starts until Claude
and the owner approve or reject it. Ollama models never review (D6). Logs go to `.task-runs/`
(gitignored).

```bash
python tools/task_runner.py status              # what is eligible or waiting for review
python tools/task_runner.py smoke               # check agent + model in about a minute
python tools/task_runner.py run                 # one task, then stop at the checkpoint
python tools/task_runner.py review T01          # review packet: diff, tests, agent report, checklist
python tools/task_runner.py approve T01 --by "Claude + owner" --note "..."
python tools/task_runner.py reject T01 --reason "what must change" [--revert]
```

A rejection reason is added to the agent's next prompt for that task.

### Writing code with GitHub Copilot

`specs/` holds a code-level spec per task (files, signatures, behaviour, tests) written for
GitHub Copilot's agent mode, which also reads `.github/copilot-instructions.md`. The spec is
binding where it is more precise than this file. Copilot's work enters the same checkpoint:

```bash
python tools/task_runner.py submit T01 --by "Copilot (<model>)" --notes "<Copilot's report>"
```

`submit` runs the tests, commits the work as `[awaiting review]` and sets the status to `review`.
Then `review`, `approve` and `reject` work as above. Copilot runs `submit` itself, then
`wait <ID> --for decision`; Claude watches with `wait <ID> --for review`. The status board is
the only channel between them. See `specs/README.md` ("The loop").

---

## 2. Rules for agents (invariants)

These come from `REQUIREMENTS.md` sections 5 and 6. A change that breaks one of them is wrong even
if its tests pass.

1. **Code owns the flow.** The state machine decides the phase, the target node, the next task and
   every transition. An LLM is a component called with a directive. It never chooses the phase,
   the node, the task or the score.
2. **Deterministic selection.** Node, review, practice and task selection are pure functions of the
   ledger and the content pack.
3. **Strict, repeatable grading.** Graders run at temperature 0 with structured output. Same input,
   same verdicts. Never free text.
4. **Append-only ledger.** Events are never edited. A verified node is never silently downgraded.
   The only operation that removes events is a whole-student privacy deletion (T80).
5. **Cite or refuse.** Every verdict, correction, tutor explanation and task result cites a passage
   that resolves back to a source document. If no passage supports it, the system says the
   question is outside the available syllabus material. No uncited general knowledge.
6. **Grading never uses similarity search.** Grading uses the passages linked to a node through its
   reviewed `source_refs`. Similarity search is only for student questions and practice lookup.
7. **Agents never author ground truth, and never set review status by hand.** Do not write
   syllabus text, and never invent answer keys or solutions. You may draft concept nodes, task
   narratives, rubrics and model answers; drafts carry `review.status = "draft"`. Only the review
   pipeline (T23) moves an item to `claude_reviewed`, from Claude's logged, quote-checked evidence
   against official sources; only a recorded human sign-off sets `signed_off`. Ollama models never
   review. Answer keys are always computed by calculator code from template parameters (owner
   decisions D1 and D6 in `HUMAN-DECISIONS.md`).
8. **The answer key never reaches the tutor LLM.** Task directives carry the brief, never the
   solution.
9. **Content is data.** Exam content, concept maps, task templates and application logic stay
   separable. A new exam attempt must be a content change, never a code change.
10. **Distraction-free kiosk.** No navigation, links out, notifications or secondary content. One
    talk affordance. New panels live inside the existing layout.
11. **Keep node IDs stable.** Eval cases, tests and ledger events reference node IDs such as
    `ind_as_115.step_4.ssp`. Never rename them.

---

## 3. Shared contracts

Parallel lanes build against these shapes. T02 turns them into Pydantic models and TypeScript
types. You may add optional fields. Do not rename or remove a field without an Open Questions row.

### 3.1 Content pack layout

```
content/packs/<pack_id>/
  manifest.json          {pack_id, exam, paper, attempt, version, topics[], doc_codes{}, out_of_scope_message}
  concept_map.json       migrated from curriculum/ind_as_115.json (+ optional `chapter` per node)
  reviews.json           {item_id: ReviewMeta}  approvals bound to a content hash (T11)
  releases.json          [ReleaseSignoff]  release sign-offs bound to the pack content hash (T11)
  sources/sources.json   [SourceDoc]  registry of source documents
  sources/raw/           original files (gitignored unless licensing is confirmed, see H1)
  corpus/chunks.jsonl    generated by scripts/ingest.py, one Passage per line
  corpus/manifest.json   {built_from{doc_id: sha256}, chunk_count, corpus_sha256}
  skills/*.json          SkillDef
  tasks/*.json           TaskTemplate
  practice_map.json      practice items (T71)
  synonyms.json          optional retrieval synonyms, e.g. "ssp" -> "standalone selling price"
```

The active pack is chosen by `CONTENT_PACK` (default `ind_as_115`). Test fixture packs live in
`services/tutor/tests/fixtures/packs/`.

### 3.2 Content models

```text
ReviewMeta   {status: "draft"|"claude_reviewed"|"needs_expert"|"signed_off", content_sha256,
              reviewer{mode: "session"|"claude-api", model}, claims[{claim, verdict, passage_id,
              quote, quote_verified}], report_id, signed_off_by, signed_off_at, notes}
ReleaseSignoff {pack_id, version, content_hash, signed_off_by, signed_off_at, scope_note}
SourceDoc    {doc_id, doc_code, title, short_name, doc_type, issuer, authority_rank, attempt,
              version, path, sha256, license_note}
             doc_type: standard | study_material | rtp | mtp | past_paper | amendment
             authority_rank: 1 = most authoritative (standard, amendment 1; study_material 2;
             rtp, mtp, past_paper 3)
Passage      {passage_id, doc_id, doc_type, paper, chapter, section, locator, attempt, version,
              page, text, sha256, supersedes[]}
Citation     {passage_id, label, doc_id}      label example: "Ind AS 115, para 76"
ScoredPassage{passage: Passage, score: float, confidence: float in [0,1]}
```

`passage_id` = `<doc_code>.<locator>`, aligned with the refs already in the concept map:
`IndAS115.para.76`, `IndAS115.para.B34`, `IndAS37.para.66`, `ICAI.SM.FR.ch4.s2.p3`,
`RTP.2025-05.q3`, `RTP.2025-05.q3.ans`.

### 3.3 Grading models

```text
ClaimJudgment  ACCURATE | INACCURATE | MISCONCEPTION | UNSUPPORTED | OFF_SYLLABUS
Claim          {claim_id, quote, node_id|null, judgment, passage_ids[]}
NodeVerdictV2  {node_id, status, confidence, evidence,
                rubric_items_met[int], misconception_ids[int],
                passage_ids[], citation_origin: "model"|"node_link"}
GraderOutput   {claims[Claim], verdicts[NodeVerdictV2], summary}
Omission       {node_id, citations[Citation]}      computed by code, never by the LLM
```

### 3.4 Ledger models

```text
LedgerEvent (concept, extends today's model)
  + kind="concept", session_id, evidence, passage_ids[], grader_call_id, content_version,
    source: diagnostic | probe | teach_back | task | review | practice
TaskAttemptEvent
  {kind="task", id, student_id, session_id, skill_id, task_id, template_version, variant_seed,
   answer_key_sha256, score, passed, item_results[{rubric_id, score, node_id, passage_ids}],
   evidence_turn_id, grader_call_id, ts}
```

### 3.5 Skills models

```text
SkillDef       {skill_id, title, description, task_ids[], unlock_rule: "all_tasks_passed"}
ParamSpec      {type: money|percent|date|int|choice|name, min, max, step, choices[]}
RubricItem     {id, text, weight, node_id, passage_ids[], required: bool,
                check: {type: "numeric", field, tolerance} | {type: "discrepancy", discrepancy_id}
                     | {type: "judgement"}}
PlantedDiscrepancy {id, row_id, issue_type, node_id, passage_ids[]}
                issue_type: premature_revenue | duplicate_billing | missing_credit_note | wrong_period | ...
TaskTemplate   {task_id, skill_id, title, kind: "calculation"|"discrepancy_hunt", node_ids[],
                company{}, narrative_template, params{name: ParamSpec}, constraints[str],
                documents[{doc_id, title, columns[], rows[]}], calculator, answer_fields[],
                rubric[RubricItem], planted_discrepancies[], model_answer_template,
                pass_threshold, template_version}
TaskVariant    {task_id, seed, params{}, narrative, documents[], answer_key{}, answer_key_sha256}
```

Review status is not stored inside skills or tasks. Like concept nodes, they are reviewed through
the pack's `reviews.json`, keyed by `skill_id` or `task_id` (T11). Parameter values, tolerances and
answer-key values are decimal or ISO-date strings so they stay exact.

### 3.6 Phases, SSE events and endpoints

- Phases today: `DIAGNOSTIC`, `INSTRUCT`, `TEACH_BACK`, `COMPLETE`. Planned additions: `TASK`
  (T53), `REVIEW` (T70), `PRACTICE` (T71). `INSTRUCT` gains a code-owned sub-step
  `instruct_step: PROBE | EXPLAIN | CONTINUE` (T40).
- SSE today: `grade`, `text`, `done`, `error`. Changes: `grade` gains `claims` and `omissions`;
  `done` gains `citations` and `grounding`; new `scope` (T42), `task` and `task_result` (T53),
  `skill` (T53), `practice` (T71). Clients must ignore unknown event kinds.
- New endpoints: `GET /content`, `GET /passages/{passage_id}`, `GET /students/{id}/ledger`,
  `GET /students/{id}/ledger/{event_id}/trace`, `GET /students/{id}/skills`,
  `GET /students/{id}/tasks/{task_id}/attempts`, `DELETE /students/{id}`, `POST /verify`.

### 3.7 New environment variables

| Var | Task | Default | Meaning |
|---|---|---|---|
| `CONTENT_PACK` | T10 | `ind_as_115` | Active content pack. |
| `REQUIRE_REVIEWED_CONTENT` | T11 | `0` | `1` refuses to teach or grade draft content. |
| `RETRIEVAL_MIN_CONFIDENCE` | T22 | calibrated | Below this, a question is out of scope. |
| `GRADER_CAPTURE_DIR` | T32 | `services/tutor/data/captures` | Where grader and task-grader calls are logged. |
| `CAPTURE_GRADER_CALLS` | T32 | `1` | `0` disables capture. |
| `GRADE_MEMO` | T32 | `1` | Memoise identical grader inputs. |
| `ALLOW_PREREQUISITE_EXPLANATIONS` | T42 | `0` | Soft mode for labelled beyond-scope background. |
| `TASKS_REQUIRE_MASTERY` | T53 | `1` | Tasks open only when their mapped nodes are verified. |
| `MAX_TASK_ATTEMPTS` | T53 | `3` | Failed attempts before a task is parked. |
| `REVIEW_INTERVALS_DAYS` | T70 | `1,3,7,21` | Spaced-repetition intervals. |
| `STORE` | T81 | `memory` | `sqlite` for the optional persistent store. |
| `SPEAKER_VERIFIER` | T82 | `stub` | Voice verification backend. |
| `REVIEWER` | T23 | `session` | `session`: Claude reviews packets in a Claude Code session. `claude-api`: Anthropic API. Ollama is refused. |
| `REVIEWER_MODEL` | T23 | the Claude model in `TUTOR_MODEL` | Claude model used when `REVIEWER=claude-api`. |
| `FLAG_THRESHOLD` | T85 | `10` | Unique student flags that open a community check (D7). |
| `COMMUNITY_CONFIRMATIONS` | T85 | `10` | "It is wrong" votes from non-flaggers needed to escalate. |
| `COMMUNITY_MAJORITY` | T85 | `0.6` | Share of decisive votes that must say "wrong" to escalate. |
| `COMMUNITY_CLOSE_VOTES` / `COMMUNITY_MAX_DAYS` | T85 | `30` / `60` | When a community check closes without escalation. |

---

## 4. Status board

Status values: `todo`, `in progress (<agent>, <date>)`, `review`, `blocked (<reason>)`,
`done (<commit>)`. Owner `human` means the domain expert or project owner does it.

| ID | Title | Lane | Depends on | Status |
|---|---|---|---|---|
| T00 | Initialise git and baseline commit | A | — | done (638b803) |
| T01 | Baseline green and housekeeping | A | T00 | done (a6f4f87, reviewed by Claude + owner) |
| T02 | Shared contracts module | A | T01 | done (7373959, reviewed by Claude + owner) |
| T10 | Content pack layout and loader | A | T02 | todo |
| T11 | Review gate | A | T10 | todo |
| T20 | Ingestion pipeline | A | T10 | todo |
| T21 | Source-ref resolver and passage API | A | T20 | todo |
| T22 | Retriever (node-linked + BM25) | A | T21 | todo |
| T23 | Grounded Claude review pipeline | A | T22, T11 | todo |
| T30 | Grader v2: claims and citations | B | T22 | todo |
| T31 | Ledger v2: student-scoped, cited, exportable | B | T30 | todo |
| T32 | Grader audit log and determinism | B | T30 | todo |
| T33 | Grader eval expansion | B | T30, T32 | todo |
| T40 | Socratic probe-first flow | C | T31 | todo |
| T41 | Tutor grounding and spoken citations | C | T40, T21 | todo |
| T42 | Syllabus boundary and confidence guard | C | T41, T22 | todo |
| T43 | Tutor bench update | C | T42 | todo |
| T50 | Skill and task schema, validator, draft templates | D | T10, T21 | todo |
| T51 | Deterministic calculators and variant generator | D | T50 | todo |
| T52 | Task grader | D | T51, T30, T32 | todo |
| T53 | TASK phase in the state machine | D | T52, T42, T31 | todo |
| T54 | Skill projection and API | D | T53 | todo |
| T60 | Web client types and SSE handling | E | T02 | todo |
| T61 | Mastery dashboard v2 | E | T60, T31 | todo |
| T62 | Citation chips on tutor turns | E | T60, T41 | todo |
| T63 | Task workspace | E | T60, T53 | todo |
| T64 | Skills panel | E | T60, T54 | todo |
| T65 | UI smoke test | E | T61, T62, T63, T64, T42 | todo |
| T66 | Flag and community-check screens | E | T60, T61, T85 | todo |
| T70 | Spaced repetition and REVIEW phase | F | T53 | todo |
| T71 | Exam-style practice from RTP/MTP/past papers | F | T70, T52, T20 | todo |
| T80 | Student data deletion and retention | F | T31, T32, T42 | todo |
| T81 | Optional SQLite store | F | T80 | todo |
| T82 | Voice verification mock endpoint | F | T01 | todo |
| T83 | Content swap proof | A | T22, T50 | todo |
| T84 | Optional seeded job profile | F | T31 | todo |
| T85 | Student flags and community check | F | T31, T41, T80 | todo |
| T86 | Professional review queue and development report | F | T85, T11 | todo |
| T90 | Demo-script acceptance test | G | T54, T42 | todo |
| T91 | Live demo runbook and latency benchmark | G | T90, T65 | todo |
| T92 | README architecture update | G | T42, T83 | todo |
| T100 | Course graph: course-agnostic packs and prerequisite edges | L | T83, T23, H6 | todo |
| T101 | Learner profile and consent | L | T80, H6 | todo |
| T102 | Placement diagnostic from graduation profile | L | T100, T101, T70 | todo |
| T103 | Goals and next-topic recommender | L | T100, T101, T70, T84 | todo |
| T104 | Signed portable ledger export | L | T31, T80, H6 | todo |
| H1 | Supply source documents and confirm licensing | human | — | todo |
| H2 | Sign off Claude's concept-map review | human | T23 | todo |
| H3 | Supply official worked illustrations; triage task review | human | T50, T23 | todo |
| H4 | Spot-check Claude-reviewed evals and practice mapping | human | T33, T71, T23 | todo |
| H5 | Sign off the retrieval threshold | human | T22 | todo |
| H6 | Owner acceptance of the MVP | human | T90, T91 | todo |

Lanes: **A** content and retrieval, **B** grading and ledger, **C** tutor, **D** skills,
**E** web UI, **F** revision, privacy and integrity, **G** acceptance and docs, **L** long-term
personalisation (post-MVP: do not start before H6).

---

## 5. Tasks

Each task lists what to read, what to build, how to prove it, and what not to do. File paths
marked *(new)* do not exist yet.

### M0 — Foundation

#### T00 — Initialise git and baseline commit
- **Requirements:** enables parallel work for every later task.
- **Read first:** `.gitignore`.
- **Build:**
  - Run `git init` at the repository root and make one baseline commit of the current tree.
  - Confirm `.gitignore` already covers `services/tutor/.env`, `services/tutor/.venv/`,
    `services/tutor/models/`, grader captures, `apps/web/node_modules/` and `.next/`.
  - Add ignore rules for `services/tutor/data/` and `content/packs/*/sources/raw/`.
- **Acceptance:** `git status` is clean after the commit. `git log` shows one commit.
- **Out of scope:** adding a remote, pushing, CI.

#### T01 — Baseline green and housekeeping
- **Requirements:** NFR auditability (health must report the right models).
- **Read first:** `README.md` (Run it, Test it), `services/tutor/tutor/llm.py`.
- **Build:**
  - Create the venv per README if missing and run the full test suite with mocks.
  - Fix `describe_grader()` in `tutor/llm.py`: for Ollama it reports `ollama_tutor_model`; it
    must report `ollama_grader_model`.
  - Replace the hard-coded test count in `README.md` with the real number.
- **Acceptance:** `pytest` passes. A new test asserts `describe_grader()` returns the grader model
  when grader and tutor models differ.
- **Out of scope:** any behaviour change.

#### T02 — Shared contracts module
- **Requirements:** enables lanes A–G to work in parallel.
- **Read first:** section 3 of this file, `tutor/models.py`, `apps/web/lib/api.ts`.
- **Build:**
  - `services/tutor/tutor/contracts/` *(new)* with `content.py`, `grading.py`, `ledger.py`,
    `skills.py`, `api.py` holding the section 3 shapes as Pydantic models. Schemas only.
  - Add the new `LedgerEvent` fields to `tutor/models.py` with safe defaults so existing code keeps
    working.
  - Do **not** change `GraderResult`, `NodeVerdict` or `Node` yet. Their JSON schema is sent to
    Ollama and `Node` is serialised into the cached prompt; changing them now would change grader
    behaviour. `GraderOutput` lives in `contracts/grading.py` until T30 switches to it.
  - Add `PROMPT_VERSION = "1"` to `tutor/prompts.py`.
  - `apps/web/lib/contracts.ts` *(new)* mirroring the models as TypeScript types. Not imported yet.
- **Acceptance:**
  - `tests/test_contracts.py` *(new)* validates one example JSON document per model.
  - All existing tests pass unchanged. `git diff` shows no change to `grader.py`,
    `state_machine.py` or `tutor_voice.py`.
- **Out of scope:** using the new models anywhere.

### M1 — Content packs and review gate

#### T10 — Content pack layout and loader
- **Requirements:** FR-2, FR-10, NFR maintainability.
- **Read first:** `tutor/curriculum.py`, `tutor/prompts.py` (`tree_block`), `tests/conftest.py`.
- **Build:**
  - Before any change, save the output of `Curriculum.stable_json()` as a golden file under
    `tests/fixtures/` *(new)*.
  - Create `content/packs/ind_as_115/` *(new)* per section 3.1. Move
    `curriculum/ind_as_115.json` to `concept_map.json` with `git mv`. Node IDs stay identical.
  - `manifest.json`: `exam: "CA Final"`, `paper: "Financial Reporting"`, `attempt: "2027-05"` (CA Final May 2027,
    owner decision), `version: "0.1.0"`, `doc_codes: {"IndAS115": ..., "IndAS37": ...}`.
  - Add optional `chapter` to `Node`. Set it to the standard's name for every node as a draft;
    T23 checks it against the sources; the owner can change it.
  - `tutor/content.py` *(new)*: `load_pack(pack_id=None)` returning a `ContentPack` (manifest,
    curriculum, paths, `content_hash`). `load_curriculum(topic_id)` keeps its signature and
    delegates to the active pack. An unknown topic still raises `FileNotFoundError` (the 404 test).
  - `stable_json()` serialises only prompt-relevant node fields (id, level, parent, title,
    rubric, misconceptions, canonical_explanation, example, source_refs). Review and chapter
    metadata never enter the prompt.
  - `GET /content` returns the manifest and `content_hash`.
- **Acceptance:**
  - The golden test proves `stable_json()` output is byte-identical to before the move.
  - Existing tests pass. An unknown `CONTENT_PACK` fails with a clear error.
- **Out of scope:** corpus, reviews, new content.

#### T11 — Review gate
- **Requirements:** FR-2 (grounded review before use), NFR accuracy and review, owner decision D1
  in `HUMAN-DECISIONS.md`.
- **Read first:** T10 output, section 2 rule 7, `HUMAN-DECISIONS.md` section 2.
- **Build:**
  - Reviews live in `reviews.json` keyed by item ID (node, task, practice item), not inline, so
    the concept-map hash stays clean. Each entry is a `ReviewMeta` with the SHA-256 of the item's
    canonical JSON. A review is valid only while that hash matches, so editing an item sends it
    back to `draft`.
  - Usable statuses are `claude_reviewed` and `signed_off`. `draft` and `needs_expert` are not.
    Strict mode also needs a `ReleaseSignoff` for the pack's current content hash (D6).
  - `REQUIRE_REVIEWED_CONTENT=1` makes `POST /session` return 409 listing unusable items in
    scope. With `0` (dev default) the service runs and `/health` and `/content` report counts per
    status for nodes, tasks and practice items.
  - `services/tutor/scripts/review_sheet.py` *(new)*: writes a Markdown report per pack with each
    item's status, reviewer verdicts, claims and quoted evidence. It lists `needs_expert` items
    first, then a random sample of `claude_reviewed` items (10% of changed items, at least 10,
    seeded so the sample is reproducible) for the human sign-off.
  - `services/tutor/scripts/record_audit.py` *(new)*: records a human check (who, date, pass or
    error with note) for given item IDs. `pass` sets `signed_off`; `error` sets `draft` and adds
    the item to the reviewer's regression set. `--release` records the `ReleaseSignoff` for the
    pack version after the owner or subject expert has read the report. Only a human runs it
    against a real pack.
- **Acceptance:** tests on a fixture pack show that an edit invalidates a review, strict mode
  refuses `draft` and `needs_expert` and any pack without a current release sign-off, the sample is
  reproducible, and a recorded error returns the item to `draft`.
- **Human gate:** H2 and H3 use the report and `record_audit.py`.

### M2 — Corpus and retrieval

#### T20 — Ingestion pipeline
- **Requirements:** FR-10.
- **Read first:** section 3.1 and 3.2, `Node.source_refs` values in the concept map.
- **Build:**
  - `services/tutor/scripts/ingest.py --pack <id>` *(new)*: reads `sources/sources.json`,
    splits each document with the splitter for its `doc_type`, and writes `corpus/chunks.jsonl`
    and `corpus/manifest.json`. Output is deterministic: the same input gives byte-identical files.
  - Splitters in `tutor/ingest/` *(new)*:
    - `standard`: one passage per numbered paragraph, including `B`, `IE` and `C` paragraphs.
      Sub-items like `(a)`, `(b)` stay inside their paragraph.
    - `study_material`: follow the heading hierarchy (`ch<n>.s<m>.p<k>`), at most about 350 words
      per chunk, never crossing a section boundary.
    - `rtp`, `mtp`, `past_paper`: one passage per question and one per answer (`q<n>`,
      `q<n>.ans`), with paper and attempt metadata.
    - `amendment`: paragraph level, with an optional `supersedes` list.
  - Input: `.txt` and `.md` are required. `.pdf` is optional behind a new extra
    `ingest = ["pypdf>=4"]` in `pyproject.toml`; keep page numbers where available.
  - A fixture pack in `services/tutor/tests/fixtures/packs/fixture_115/` *(new)* with synthetic
    documents. Every fixture passage starts with `[TEST FIXTURE - NOT SYLLABUS TEXT]`.
- **Acceptance:** splitter unit tests per doc type; passage IDs are unique; running ingest twice
  gives the same `corpus_sha256`.
- **Out of scope:** OCR, embeddings, writing real syllabus text.
- **Human gate:** real sources come from H1. Until then, only the fixture pack has a corpus.

#### T21 — Source-ref resolver and passage API
- **Requirements:** FR-3 and FR-10 ("a citation must resolve back to the source document and
  passage").
- **Read first:** every distinct `source_refs` form in `concept_map.json`.
- **Build:**
  - `tutor/retrieval/refs.py` *(new)*: parse and resolve refs. It must handle every form in the
    current map: `IndAS115.para.9-16` (range in document order), `IndAS115.para.22(b)` (resolves
    to para 22, label keeps "(b)"), `IndAS115.para.B28-B33`, and cross-standard
    `IndAS37.para.66-69`. The doc code maps to a document through `manifest.doc_codes`.
  - Citation labels: "Ind AS 115, para 76", "Ind AS 115, paras 76–77", "ICAI Study Material,
    Ch 4 §2", "RTP May 2025, Q3 (answer)".
  - `GET /passages/{passage_id}` returns the passage and its source document metadata, or 404.
  - `services/tutor/scripts/validate_pack.py --pack <id>` *(new)*: exits non-zero and lists
    every node ref that resolves to no passage.
- **Acceptance:** parser tests for each form above; API test; the validator passes on the fixture
  pack and fails on a deliberately broken ref. On the real pack the test is skipped with a
  logged reason while the corpus is missing.

#### T22 — Retriever
- **Requirements:** FR-10 ("compact index, node-linked first, similarity for lookup"), FR-11.
- **Read first:** T21 output.
- **Build:**
  - `tutor/retrieval/retriever.py` *(new)*: a `Retriever` protocol with `for_node(node_id)`
    (node-linked, deterministic, document order) and `search(query, k, filters)` returning
    `ScoredPassage` items.
  - `BM25Retriever` in pure Python, with no heavy new dependency. Lower-case tokens, keep
    paragraph numbers, drop common English stopwords, expand terms from the pack's
    `synonyms.json`. Build the index at pack load and cache it by `corpus_sha256`. Break ties by
    `passage_id`.
  - Map raw scores to a `confidence` in [0, 1]. Choose the method, document it in the module
    docstring, and make it stable across queries.
  - Filters: `doc_type`, `attempt`, `chapter`, `node_ids`.
  - `services/tutor/scripts/calibrate_retrieval.py` *(new)* and
    `tests/evals/retrieval/queries.jsonl` *(new)*: in-syllabus questions with expected passage
    IDs, and out-of-syllabus questions (for example Ind AS 116 leases, GST rates, US GAAP). The
    script reports recall@5 and the threshold that best separates the two groups.
- **Acceptance:** ordering is deterministic across runs; recall@5 is at least 0.8 on fixture
  queries; fixture out-of-syllabus queries score below the suggested threshold.
- **Human gate:** H5 signs off the threshold for the real pack.

#### T23 — Grounded Claude review pipeline
- **Requirements:** FR-2, FR-12, NFR accuracy and review, owner decisions D1 and D6 and the
  safeguards in `HUMAN-DECISIONS.md` section 2.
- **Read first:** `HUMAN-DECISIONS.md` sections 1 and 2, `QUALITY-AND-REVIEW.md` section 3, T11 and
  T22 output, `tutor/grader.py` (the Claude structured-output pattern in `ClaudeGrader`).
- **Build:**
  - `services/tutor/scripts/content_review.py --pack <id> [--items ...]` *(new)* reviews every item
    whose status is `draft` or whose hash changed: concept nodes now, task templates after T50,
    practice items after T71, eval expectations after T33.
  - Claim split: code splits each item into claims (each rubric item, each sentence of the
    explanation and example, each misconception, each task answer step). Misconceptions are
    checked as "the source contradicts this".
  - Evidence: for each claim, code collects candidate passages from the item's `source_refs`
    first, then `search()` restricted to sources of equal or higher `authority_rank`, and writes an
    evidence packet (claims plus passages with IDs).
  - **The reviewer is Claude only (D6).** `REVIEWER` selects how:
    - `session` (default, development): packets are written to
      `services/tutor/data/reviews/pending/` as Markdown plus a JSON answer file. Claude fills the
      answers in a Claude Code session with the owner; `content_review.py --ingest` validates and
      applies them.
    - `claude-api` (scale): the same packets go to the Anthropic API (`REVIEWER_MODEL`) with
      structured output at temperature 0.
    - Any Ollama model or provider is refused with an error. There is no Ollama code path.
  - Per claim the answer is `supported | contradicted | not_found`, a passage ID and a verbatim
    quote. Code checks the quote appears word for word, after whitespace normalisation, in that
    passage; a failed check makes the claim `not_found`.
  - An item becomes `claude_reviewed` only if every claim is supported with a verified quote.
    Otherwise it becomes `needs_expert`, with the reasons in the report.
  - Coverage check for concept nodes: the reviewer lists any rule in the node's cited passages that
    the rubric omits and a student would need; any gap makes the node `needs_expert`.
  - Answer keys: for each calculator, run the official worked illustrations in
    `tests/skills/reference_cases/`; a mismatch makes the task `needs_expert`.
  - Every run writes a report under `services/tutor/data/reviews/` and updates `reviews.json`
    through T11's code path only.
  - Reviewer test set `tests/evals/review/` *(new)*: fixture nodes with planted errors (wrong
    paragraph, reversed rule, invented exception, missing rubric item). `--self-test` produces
    packets (session) or runs them (API); Claude must catch at least 95% before its reviews count.
- **Acceptance:** on the fixture pack with a scripted reviewer: clean items become
  `claude_reviewed`, planted-error items become `needs_expert`, a fabricated quote fails the quote
  check, the session round trip (packet, filled answers, `--ingest`) works, and configuring an
  Ollama reviewer fails. A mock reviewer keeps the path runnable with `MOCK_LLM=1`.
- **Out of scope:** changing content to fix what the reviewer finds; that is a drafting step.
- **Human gate:** H2: the owner reads the report, checks the sample and every `needs_expert` item,
  and records the release sign-off.

### M3 — Cited, claim-level grading

#### T30 — Grader v2: claims and citations
- **Requirements:** FR-3, FR-6, AC2, AC4, AC7.
- **Read first:** `tutor/grader.py`, `tutor/prompts.py`, `tests/evals/grader/`,
  `contracts/grading.py`.
- **Build:**
  - Add a second cached system block after the tree block: every passage linked to any node, in
    stable order, each wrapped as `<passage id="...">text</passage>`. Instructions stay after the
    cache breakpoint. Measure its token size. If it exceeds about 30k tokens, send only the focus
    node's passages on teach-back calls and record the decision in the Open Questions log.
  - Rewrite `GRADER_INSTRUCTIONS`: split the student's speech into claims; judge each claim only
    against the passages and rubric; list the rubric items met, the misconceptions matched and the
    supporting passage IDs per verdict; flag off-syllabus claims without grading them. Keep the
    existing strictness rules verbatim, including "name-dropping is not evidence".
  - Switch all three graders to `GraderOutput`: `ClaudeGrader` via `messages.parse`,
    `OllamaGrader` via schema plus an updated `OLLAMA_OUTPUT_CONTRACT`, and `MockGrader` which
    emits one claim per matched node with `node_link` citations.
  - Extend `_finalise()`: drop passage IDs outside the node's linked set; attach the node's first
    linked passage with `citation_origin="node_link"` when a graded verdict has none; drop rubric
    and misconception indexes out of range; count every correction for the audit log.
  - Code computes omissions after a diagnostic: every L1 node with no evidence, with its node
    citations. The `grade` SSE event carries `claims` and `omissions`.
  - Bump `PROMPT_VERSION`.
- **Acceptance:**
  - Unit tests for `_finalise()` with unknown nodes, foreign passages and bad indexes.
  - State-machine tests and the mock HTTP loop pass.
  - `run_evals.py --repeat 3` on the configured model passes at least as many cases as before
    (28/28 on `gemma4:31b-cloud`, per README). Record the numbers, or state that no model was
    available and set the status to `review`, not `done`.
- **Out of scope:** similarity retrieval inside grading.

#### T31 — Ledger v2: student-scoped, cited, exportable
- **Requirements:** FR-7, FR-13, NFR traceability.
- **Read first:** `tutor/ledger.py`, `tutor/store.py`, `tutor/main.py`.
- **Build:**
  - Today the ledger lives on each `Session`. FR-7 needs one ledger per student across sessions.
    Add a `LedgerStore` protocol (`append`, `events_for(student_id)`, `delete_student`) with an
    in-memory implementation. `SessionView.ledger` shows this session's events; the mastery
    projection uses all of the student's events, so a returning student is not re-taught verified
    nodes.
  - Fill the new event fields from the grader output: `evidence`, `passage_ids`,
    `grader_call_id`, `content_version`, `source`, `session_id`.
  - Keep today's rules: `NOT_MENTIONED` is not written, and a VERIFIED node is overwritten only by
    a focused verdict (teach-back, probe, review, task remediation). Document in `ledger.py` that
    a focused downgrade is explicit and evidence-linked, never incidental.
  - `GET /students/{id}/ledger` returns the pitch reference shape (`VERIFIED`→`MASTERED`,
    `GAP`→`GAP_IDENTIFIED`, `PARTIAL`→`PARTIAL`, no event→`NOT_ASSESSED`) with confidence, last
    timestamp, evidence turn and citation labels, plus the raw `events` list.
  - `GET /students/{id}/ledger/{event_id}/trace` returns the event, the exact student turn text,
    the cited passages and the grader call ID.
- **Acceptance:** tests for cross-session projection, blocked incidental downgrade, allowed and
  recorded focused downgrade, export status mapping, and a trace that returns the exact turn text.

#### T32 — Grader audit log and determinism
- **Requirements:** NFR auditability and determinism, AC7.
- **Read first:** `_capture()` in `tutor/grader.py`, `tests/evals/grader/run_evals.py`.
- **Build:**
  - Each capture adds `grader_call_id`, `student_id`, `prompt_version`, `content_hash`, the SHA-256
    of the system prompt, the focus node rubric, the passage IDs offered, the `_finalise`
    correction count and latency. The call ID is returned to the caller and written on ledger
    events.
  - Captures move to `GRADER_CAPTURE_DIR`. `CAPTURE_GRADER_CALLS=0` disables them.
  - A grade memo keyed by SHA-256 of (content hash, prompt version, provider, model, focus node,
    prior context, transcript) returns the stored result for an identical input. `GRADE_MEMO=0`
    disables it.
  - `run_evals.py` gains `--no-memo` (the default for evals, so raw model determinism is measured)
    and compares statuses **and** passage IDs across `--repeat` runs, printing per-case diffs.
- **Acceptance:** a test with a call-counting scripted grader shows the second identical call hits
  the memo; captures contain `student_id`; the eval runner reports inconsistent citations.

#### T33 — Grader eval expansion
- **Requirements:** AC2, AC4, AC7, FR-3.
- **Read first:** `tests/evals/grader/_make_cases.py` and the existing cases.
- **Build:**
  - Case schema gains optional `expect_citations` (node ID → passage ID prefixes) and
    `expect_omissions`.
  - New cases, with fictional student speech written by the agent:
    - The AC1/AC2 diagnostic: explains steps 1, 2, 3 and 5, says revenue is recognised on
      invoicing, and omits allocation. Expect `ind_as_115.step_5` as `GAP` with its "invoicing or
      cash receipt" misconception, `ind_as_115.step_4` as `NOT_MENTIONED` and listed in omissions.
    - The AC4 teach-back: extend case 03 (allocates on cost) with citation expectations.
    - One multi-claim answer that mixes an accurate and an inaccurate claim on the same node.
    - STT-noisy speech that must still verify, with citations.
  - New cases start as `draft`; T23 reviews each expected verdict and citation against the
    sources before the case counts.
  - Run against the configured model with `--repeat 3` and update the README results table.
  - You may iterate the grader prompt (bumping `PROMPT_VERSION` and re-running every case), but
    never weaken the strictness rules.
- **Human gate:** H4 spot-checks the AI-reviewed cases.

### M4 — Socratic, grounded tutor

#### T40 — Socratic probe-first flow
- **Requirements:** FR-5 ("ask a probing question before revealing the answer"), FR-6, AC3.
- **Read first:** `tutor/state_machine.py`, `tests/test_state_machine.py`, `tutor/tutor_voice.py`
  (`MockTutor`).
- **Build:**
  - Add `instruct_step: PROBE | EXPLAIN | CONTINUE` to `Session`.
  - When code selects a new target node, the first tutor turn is a probe: directive
    `ACTION=PROBE` asks one question that leads toward the first unmet rubric item, states no rule,
    at most 60 words, and does not request a teach-back. Include known grader evidence or the
    matched misconception.
  - The student's reply to a probe gets a focused grade (`source="probe"`). Then:
    VERIFIED writes the event and advances; PARTIAL gives an `EXPLAIN` limited to the missing
    rubric items; GAP or NOT_MENTIONED gives a full `EXPLAIN` that corrects the misconception.
  - Code gates the teach-back sentinel. Today the tutor can move INSTRUCT→TEACH_BACK on any turn
    by emitting `<<TEACH_BACK>>`. Honour it only when the rules allow (never during `PROBE`, never
    on the first `EXPLAIN` turn); otherwise strip and ignore it. The max-turns force stays.
  - `MockTutor` handles `ACTION=PROBE`. Update the README state diagram.
- **Acceptance:** tests show the first turn on a new node is a probe with no explanation; probe
  VERIFIED advances; probe GAP leads to EXPLAIN; a sentinel during PROBE does not change phase;
  `test_api_mock.py` is updated and passes.

#### T41 — Tutor grounding and spoken citations
- **Requirements:** FR-5, FR-6 ("corrections cite the exact reviewed source passage"), AC3, AC4.
- **Read first:** T40 output, `tutor/prompts.py` (`TUTOR_INSTRUCTIONS`).
- **Build:**
  - Every INSTRUCT directive carries the target node's passages from `for_node()` with their
    labels. `TEACH_BACK_FAILED` also carries the matched misconception, the student's claim quote
    and its passage.
  - Update `TUTOR_INSTRUCTIONS`: explain only from the provided passages and node fields; when
    stating a rule, say its label once in natural speech ("Paragraph 76 of Ind AS 115 says…");
    never cite a label that was not provided; never invent paragraph numbers.
  - The `done` event carries `grounding` (passages provided) and `citations` (provided passages the
    tutor actually mentioned, matched by label or paragraph number).
  - Code scans tutor text for paragraph references that were not provided and records
    `uncited_reference` on the turn. It does not block speech; T43 counts it.
- **Acceptance:** scripted-tutor tests show passages in directives; unit tests for citation
  matching; `MockTutor` mentions a label on explain turns.

#### T42 — Syllabus boundary and confidence guard
- **Requirements:** FR-11, AC8.
- **Read first:** T22 and T41 output.
- **Build:**
  - `tutor/scope.py` *(new)*: deterministic `is_question(text)` that works on STT text without
    punctuation (leading interrogatives, "can you explain", "what about", "tell me about").
  - In INSTRUCT and COMPLETE, a question is sent to `search()`. Emit a `scope` SSE event with the
    result.
    - If the top confidence is below `RETRIEVAL_MIN_CONFIDENCE` and the question does not match the
      target node's passages, code streams the pack's fixed `out_of_scope_message` (for example
      "That's outside the syllabus material I have for this topic, so I won't guess."), then the
      tutor continues with `ACTION=RETURN_TO_TARGET`. Log the question, student, session, turn
      and top scores to `data/off_syllabus/` for curation.
    - Otherwise use `ACTION=ANSWER_QUESTION` with the retrieved passages, then return to the target.
  - With `ALLOW_PREREQUISITE_EXPLANATIONS=1`, an out-of-scope question may instead get
    `ACTION=PREREQUISITE_BEYOND_SCOPE`: it must open with a fixed "beyond the current syllabus"
    label sentence, stay under 60 words, and never call the grader or write ledger events.
- **Acceptance:** tests show an out-of-syllabus question streams the fixed sentence with no
  citations and writes the log; an in-scope question puts retrieved passages in the directive;
  soft mode carries the label and writes no ledger event; the threshold comes from the environment.

#### T43 — Tutor bench update
- **Requirements:** FR-5, NFR latency.
- **Read first:** `tests/evals/tutor/bench_tutor.py`.
- **Build:** add scripted directives for PROBE, EXPLAIN with passages, ANSWER_QUESTION,
  RETURN_TO_TARGET and PREREQUISITE. New metrics: a probe states no rule and ends with a question;
  an explain turn cites a provided label; no unprovided paragraph numbers; at most 120 words; ends
  with one question.
- **Acceptance:** the bench runs on the configured tutor model(s) and the README table is updated.

### M5 — Skills

#### T50 — Skill and task schema, validator, draft templates
- **Requirements:** FR-12.
- **Read first:** section 3.5, `REQUIREMENTS.md` FR-12, the concept map node list.
- **Build:**
  - `content/packs/ind_as_115/skills/revenue_recognition_services.json` *(new)*: one skill,
    "Revenue recognition for a service-based company", with four task IDs.
  - Four draft task templates in `tasks/` *(new)*, all `review.status = "draft"`, with narrative,
    rubric and model-answer text drafted for T23 review. Use one fictional mid-size Indian IT
    services company across all four tasks (see `HUMAN-DECISIONS.md` section 7):
    1. `rr_fixed_price_cost_to_cost` — fixed-price implementation contract, cost-to-cost input
       method, revenue to date and contract asset or liability at period end. Nodes include
       `step_5.over_time_criteria`, `step_5.measuring_progress`, `cross_cutting.presentation`.
    2. `rr_contract_modification` — scope change mid-contract; separate contract, prospective or
       cumulative catch-up. Nodes include `step_1.modification`.
    3. `rr_variable_consideration` — performance bonus or SLA penalty; expected value versus most
       likely amount; the constraint. Nodes include `step_3.variable_consideration`,
       `step_3.constraint`.
    4. `rr_discrepancy_hunt` — an invoice register and GL extract with planted premature revenue,
       duplicate billing, a missing credit note and wrong-period recognition.
    The owner may swap in time-and-materials billing or an onerous contract later; that is a
    content change only. Use the grading defaults in `HUMAN-DECISIONS.md` section 7.3 unless the
    owner changed them.
  - Extend `validate_pack.py`: node IDs exist, passage IDs resolve, the calculator is registered,
    rubric weights sum to 1.0, planted discrepancies point at real document rows, every narrative
    placeholder has a parameter, and constraints parse.
  - Constraints use a tiny safe expression evaluator (comparison and arithmetic on parameters).
    Never Python `eval`.
- **Acceptance:** schema tests; the validator passes on the drafts (passage checks are skipped with
  a warning while the real corpus is missing) and fails on broken fixtures.
- **Human gate:** T23 reviews the drafts; H3 supplies official worked illustrations and triages
  `needs_expert` items.

#### T51 — Deterministic calculators and variant generator
- **Requirements:** FR-12 ("calculations must be deterministic code"), AC7.
- **Read first:** T50 templates.
- **Build:**
  - `tutor/skills/calculators.py` *(new)*: pure functions using `Decimal` with explicit rounding.
    Each docstring names the paragraphs it implements. Needed at least: cost-to-cost progress and
    revenue, contract asset or liability; contract modification treatment and catch-up amount;
    variable consideration (expected value, most likely amount, constrained amount); and a
    cut-off checker for the hunt that confirms each planted issue appears in the generated data
    and no unplanned issue does. Register them by name.
  - `tutor/skills/variants.py` *(new)*: `generate_variant(template, seed)` using
    `random.Random(seed)`. Sample parameters from their specs, reject-sample until constraints
    hold (fail loudly after a bounded number of tries), pick names from template lists, and set
    `answer_key = calculator(params)` with its SHA-256. No LLM.
  - `tests/skills/reference_cases/` *(new)* holds official worked illustrations with published
    solutions (for example ICAI study-material illustrations), transcribed with their source
    passage IDs. H3 supplies the sources. Agents may write arithmetic unit tests; they may not
    invent reference answers.
- **Acceptance:** property tests over 500 seeds per template: constraints hold, the answer key
  recomputes identically, the same seed gives an identical variant hash, and every planted
  discrepancy is detectable with no extra anomalies. Reference cases, once supplied, pass exactly.

#### T52 — Task grader
- **Requirements:** FR-12 ("rubric-based, partial credit, citations"), AC5.
- **Read first:** T30 grader, T51 variants, section 3.5.
- **Build:**
  - `tutor/skills/task_grader.py` *(new)* with a `TaskGrader` protocol and Claude, Ollama and Mock
    implementations.
  - Step 1, extraction (LLM, temperature 0, structured): the numbers stated per answer field, the
    discrepancies found (row, issue type, quote), and reasoning quotes. Code normalises spoken
    amounts, including lakh, crore, "k" and percentages.
  - Step 2, deterministic checks: numeric items score 1 within tolerance, else 0. Discrepancy items
    score 1 for the right row and issue type, 0.5 for the right row only.
  - Step 3, judgement items (LLM, temperature 0): each item is judged against the model answer and
    the item's passages, returning full, partial or none, an evidence quote and passage IDs from the
    item's set only.
  - Score is the weighted sum. `passed` requires the score to reach `pass_threshold` and every
    `required` item to be met. Failing items carry their `node_id` and citations for routing.
  - Reuse the T32 capture and memo, with `kind="task"`.
- **Acceptance:** tests with scripted extraction cover partial-credit arithmetic, tolerance edges
  and discrepancy matching; the mock path works end to end; `tests/evals/tasks/` *(new)* has at
  least four cases (correct, one numeric error, a missed discrepancy, wrong reasoning), which
  start as `draft` until T23 reviews them.

#### T53 — TASK phase in the state machine
- **Requirements:** FR-12, FR-13, AC5, AC6.
- **Read first:** `tutor/state_machine.py` after T42, T52 output.
- **Build:**
  - Add phase `TASK` and session fields `active_task` (task ID and seed), `return_to_task`, and
    `mode: learn | skills` on `CreateSessionRequest`.
  - Entry: when node selection finds nothing left, pick the next task not yet passed whose mapped
    nodes are all VERIFIED (or any such task when `TASKS_REQUIRE_MASTERY=0`). `mode=skills` starts
    a session directly on the first available task, for the demo.
  - Presenting a task: code emits a `task` event (title, narrative, documents, answer fields,
    remaining tasks). The tutor gets `ACTION=PRESENT_TASK` with the brief only, at most 80 spoken
    words. The answer key and model answer are never in any directive.
  - Grading a task answer writes a `TaskAttemptEvent` and emits `task_result`.
    - Pass: move to the next task, or emit `skill` when the skill unlocks.
    - Fail (owner decision, `HUMAN-DECISIONS.md` 7.4): name the first failing item with its
      citation. Do **not** write a concept downgrade. If every failing item is numeric and the
      student's reasoning items passed, it is an arithmetic slip: offer a retry only. Otherwise
      record the failing item's node as a review request on the `TaskAttemptEvent` (T70's
      scheduler picks these up once it exists), set it as the target and run the normal probe,
      explain and teach-back loop; that teach-back verdict changes mastery, with evidence.
      When that node is verified or parked, return to the task with a new seed derived from
      student, task and attempt number.
    - After `MAX_TASK_ATTEMPTS` failures the task is parked.
- **Acceptance:** tests for the pass path, fail → teach-back → return with a new variant, a check
  that no directive ever contains answer-key values, unlock after all tasks pass, and parking.

#### T54 — Skill projection and API
- **Requirements:** FR-12 ("show skill state and remaining tasks"), FR-13, NFR traceability, AC6.
- **Build:**
  - `project_skills(events, pack)`: per skill, `locked` (no task available), `in_progress`
    (something available or attempted, not all passed) or `unlocked` (all passed), with each
    task's state and the remaining count.
  - `GET /students/{id}/skills`.
  - `GET /students/{id}/tasks/{task_id}/attempts`: template version, template review hash, rubric,
    `answer_key_sha256`, seed, grader call ID and evidence turn. Return the hash, not the key.
- **Acceptance:** projection tests for all three states; API tests.

### M6 — Kiosk UI

All UI tasks: keep one talk affordance, no navigation, no links out. Read the Next.js docs first
(section 1, Commands).

#### T60 — Web client types and SSE handling
- **Requirements:** FR-1, FR-8.
- **Build:** switch `apps/web/lib/api.ts` to the `contracts.ts` types; handle the new SSE kinds and
  ignore unknown ones; add `getPassage`, `getStudentLedger` and `getSkills`; add the new phases to
  `PHASE_LABEL` in `app/page.tsx`. Develop against recorded SSE fixtures until the backend lands.
- **Acceptance:** lint and build pass; a test or fixture replay shows unknown events are ignored.

#### T61 — Mastery dashboard v2
- **Requirements:** FR-8, FR-13 ("mastery by chapter"), AC2.
- **Build:** in `components/MasteryGrid.tsx`, group by chapter when there is more than one;
  highlight omissions after the diagnostic; clicking a chip opens an evidence panel inside the
  rail with status, confidence, the student's quote and each citation's passage text from
  `/passages`. Escape closes it. Updates stay live.
- **Acceptance:** lint and build pass; a manual check with `MOCK_LLM=1` shows evidence and citations;
  the panel is keyboard accessible.

#### T62 — Citation chips on tutor turns
- **Requirements:** FR-5, FR-6, AC3, AC4.
- **Build:** in `components/Transcript.tsx`, show a small label chip for each citation on a tutor
  turn. Clicking opens the same rail panel as T61.
- **Acceptance:** lint and build pass; manual check with the mock backend.

#### T63 — Task workspace
- **Requirements:** FR-12, AC5.
- **Build:** during `TASK`, the main column shows a task card (title, narrative, document tables,
  the fields to state). After grading it shows a score bar and each rubric item as met, partial or
  missed with feedback and citations. When routed to remediation, a line names the concept being
  revisited. Voice and text answers both work.
- **Acceptance:** lint and build pass; manual check with the mock backend.

#### T64 — Skills panel
- **Requirements:** FR-12, FR-13, AC6.
- **Build:** a rail section under the mastery grid showing the skill state, each task's state and
  the remaining count, with a restrained unlock moment.
- **Acceptance:** lint and build pass; manual check with the mock backend.

#### T65 — UI smoke test
- **Requirements:** FR-1, FR-8, AC5, AC6.
- **Build:** a Playwright test in `apps/web/e2e/` *(new)* and an `e2e` npm script, running against a
  `MOCK_LLM=1` backend: begin a session, type a diagnostic, see the grade and chips, open a
  citation, complete a task, see the skill unlock. A `?mode=skills` URL parameter is allowed for
  the demo only and must not add visible navigation.
- **Acceptance:** `npm run e2e` passes locally.

#### T66 — Flag and community-check screens
- **Requirements:** FR-14, NFR distraction-free, D7, `QUALITY-AND-REVIEW.md` section 4.
- **Build:**
  - A small "I think this is wrong" control on tutor turns, on the evidence panel (T61) and on task
    results (T63). It asks for a short reason (typed or spoken) and confirms the flag.
  - An end-of-session card for community checks: the item, its cited passage, the anonymous reasons
    so far, a caution line ("check the source before you vote"), and three choices ("It is wrong",
    "It is correct", "Not sure") with a reason for the first two. Never shown mid-lesson.
  - The student's own flags and their outcomes, inside the rail.
- **Acceptance:** lint and build pass; the T65 Playwright test is extended with a flag and a vote
  against the mock backend.

### M7 — Revision and practice

#### T70 — Spaced repetition and REVIEW phase
- **Requirements:** FR-13 ("resurface weak concepts through spaced repetition").
- **Build:**
  - `tutor/revision.py` *(new)*: `due_reviews(events, now)` over the student ledger using
    `REVIEW_INTERVALS_DAYS`. Each VERIFIED node's next review date depends on its count of
    consecutive successful reviews. The clock is injectable.
  - A returning student with a non-empty ledger skips the diagnostic. If reviews are due, the
    session starts in `REVIEW` with a code-built prompt ("Quick review: explain … with an
    example"). Grade it as a focused verdict with `source="review"`. Pass schedules the next
    interval; fail makes the node the INSTRUCT target. After reviews, the selector continues.
- **Acceptance:** fake-clock tests for scheduling, due reviews served before new nodes, and a
  returning student skipping the diagnostic.

#### T71 — Exam-style practice from RTP/MTP/past papers
- **Requirements:** FR-13 ("exam-style practice … retaining exact source citations").
- **Build:**
  - `practice_map.json`: `{item_id, question_passage_id, answer_passage_id, node_ids, marks,
    review}`. `scripts/suggest_practice_map.py` *(new)* may propose mappings with BM25; only
    reviewed items are used in strict mode.
  - Phase `PRACTICE` after COMPLETE or after reviews when weak nodes have mapped items. Choose
    deterministically: weakest node first, then source recency.
  - Emit a `practice` event with the full question text for the main column. The tutor reads a
    short brief with the source label ("From the RTP for May 2025, question 3").
  - Grade with the T52 judgement path against the official answer passage and the node rubric.
    Write concept events with `source="practice"`.
- **Acceptance:** tests on fixture Q/A passages; every practice result cites its question and
  answer passages; unreviewed items are never used in strict mode.
- **Human gate:** T23 reviews the mapping; H4 spot-checks it.

### M8 — Privacy, integrity, portability

#### T80 — Student data deletion and retention
- **Requirements:** NFR privacy.
- **Build:** `DELETE /students/{id}?confirm=true` purges the student's sessions, ledger events,
  grader and task captures, off-syllabus log entries and memo entries, and returns counts.
  Document that this is the only operation that removes ledger events. Confirm no code path
  stores audio. Document `CAPTURE_GRADER_CALLS=0` for any non-local deployment.
  - Retention (owner decision, `HUMAN-DECISIONS.md` 11.2): a `consent_research` flag on the
    student. A scheduled purge strips `student_id` from grader captures after 90 days when consent
    is given, and deletes them after 90 days when it is not. It strips `student_id` from the
    off-syllabus log after 30 days. Retention periods are configuration.
- **Acceptance:** a test creates data for two students, deletes one, and shows every artifact of
  that student is gone while the other's are intact. A fake-clock test shows the retention purge
  de-identifies or deletes captures according to consent.
- **Security note:** the API has no authentication. Record in section 10 that it must not be
  exposed beyond localhost until auth exists.

#### T81 — Optional SQLite store
- **Requirements:** REQUIREMENTS section 7 (persistence optional).
- **Build:** SQLite implementations of `SessionStore` and `LedgerStore` behind `STORE=sqlite`,
  including deletion.
- **Acceptance:** the full test suite passes with `STORE=sqlite`; the deletion test passes.

#### T82 — Voice verification mock endpoint
- **Requirements:** FR-9.
- **Build:** `POST /verify` accepts a student ID and audio and returns `{match, score, method}`
  through `SpeakerVerifier` selected by `SPEAKER_VERIFIER`. The stub always matches.
- **Acceptance:** a conformance test any verifier must pass (score in [0, 1], stable shape).

#### T83 — Content swap proof
- **Requirements:** FR-10 ("swap … without code changes"), NFR maintainability.
- **Build:** a second fixture pack `fixture_115_v2` *(new)* with a different attempt and one amended
  passage. Add a README section "Releasing a new attempt" listing the content-only steps.
- **Acceptance:** tests switch `CONTENT_PACK` and show the new version in `/content`, the amended
  text in `/passages`, a changed grader prompt hash, and stable node IDs, with no code changes.

#### T84 — Optional seeded job profile
- **Requirements:** REQUIREMENTS section 9 (only if it costs nothing).
- **Build:** `content/packs/ind_as_115/job_profiles/*.json` with the section 9 shape; a
  "qualified" projection (every required node VERIFIED); an optional job-profile filter on the
  node selector that walks core nodes before adjacent ones.
- **Acceptance:** projection and selector filter tests.

#### T85 — Student flags and community check
- **Requirements:** FR-14, D7, NFR privacy, `QUALITY-AND-REVIEW.md` section 4,
  `HUMAN-DECISIONS.md` section 12.
- **Build:**
  - Models: `Flag {id, student_id, item_ref{kind: node|rubric_item|task_item|passage_link|
    practice_item, id, content_sha256}, context{session_id, turn_id, ledger_event_id}, reason, ts}`;
    `Vote {id, student_id, item_ref, choice: wrong|correct|not_sure, reason, ts}`;
    `Case {item_ref, state: collecting|community_check|professional_review|confirmed_error|rejected|
    closed_no_consensus, counts, opened_at}`. Case transitions are code, driven by the thresholds in
    section 3.7.
  - Store behind an interface (in memory; SQLite with T81).
  - Endpoints: `POST /flags`, `GET /students/{id}/flags` (with outcomes),
    `GET /students/{id}/community-checks` (open checks the student may vote on), `POST /votes`.
  - Eligibility: the student has ledger events on the item's node, or an attempt on the task. One
    flag and one vote per student per item (409 on a repeat). A reason is required for flags and
    for "wrong" or "correct" votes.
  - Turn, grade and task payloads carry the `item_ref` of everything a student can flag.
  - When a case enters professional review, append a `disputed` annotation event for every
    ledger event that used the item. Nothing is edited.
  - `DELETE /students/{id}` (T80) also removes that student's flags and votes and recomputes counts.
- **Acceptance:** fake-clock tests: nine flags change nothing and the tenth opens a community check;
  a repeat flag and an ineligible voter are refused; the confirmation threshold escalates; a
  minority result closes the case; disputed events are appended with no edits; deleting a student
  recomputes counts.

#### T86 — Professional review queue and development report
- **Requirements:** FR-14, AC9, D6, D7.
- **Build:**
  - Admin API, localhost only until authentication exists: `GET /admin/review-queue`,
    `GET /admin/cases/{id}` (item, source passages, flag reasons, votes, affected ledger events),
    `POST /admin/cases/{id}/decision {decision: confirmed_error|rejected, explanation, reviewer,
    pause}`.
  - `confirmed_error`: the item returns to `draft` through T11 (so it is fixed and reviewed again),
    is excluded from use if `pause` is set, affected ledger events receive explicit corrective
    events linked to the case, and flaggers and voters see the outcome.
  - `rejected`: the case closes and the explanation is shown to flaggers and voters.
  - `services/tutor/scripts/flags_report.py` *(new)*: a Markdown report of cases in professional
    review, for the development session with Claude and the owner. `decide_case.py` records a
    decision through the same code as the admin API.
  - A minimal admin page at a separate `/admin` route in `apps/web`, outside the kiosk flow.
- **Acceptance:** tests show a confirmed error sets the item to `draft`, appends corrective events
  and publishes the outcome; a rejection publishes its explanation; the report lists open cases;
  admin endpoints refuse non-localhost requests.

### M9 — Acceptance and docs

#### T90 — Demo-script acceptance test
- **Requirements:** AC1–AC8.
- **Build:** `services/tutor/tests/test_demo_script.py` *(new)* drives the HTTP API with scripted
  grader, tutor and task grader on the fixture pack. One test per criterion: `test_ac1_…` to
  `test_ac8_…`, following REQUIREMENTS section 10 step by step.
- **Acceptance:** all eight tests pass in the default `pytest` run.

#### T91 — Live demo runbook and latency benchmark
- **Requirements:** NFR latency, AC1–AC8 on real models.
- **Build:** `tests/evals/latency/bench_turn.py` *(new)* measures grade plus first text delta over
  HTTP. A README "Demo" section gives the live demo steps with voice.
- **Acceptance:** the benchmark results table is in the README; the live demo has been walked
  through once with the configured models, or the commit says which steps could not be run.

#### T92 — README architecture update
- **Requirements:** REQUIREMENTS section 13.
- **Build:** replace "Why there is no RAG in the MVP" with the node-linked retrieval design
  (grading uses node-linked passages and stays deterministic; similarity search only serves
  questions and practice). Document content packs, the review flow and the new endpoints.
- **Acceptance:** every command in the README runs as written.

### M10 — Long-term: personalised learning beyond exams (post-MVP)

Owner decision D2 in `HUMAN-DECISIONS.md`: Teach is not limited to exams. Do not start these tasks
before H6 (owner acceptance of the MVP). They are specified here so earlier work does not block them.

#### T100 — Course graph: course-agnostic packs and prerequisite edges
- **Requirements:** REQUIREMENTS section 9 (personalised learning beyond exams), D2.
- **Read first:** T10 and T83 output, `HUMAN-DECISIONS.md` section 10.
- **Build:**
  - Generalise the pack manifest from "exam attempt" to "course version": `course_id`, `kind`
    (`exam | graduation | professional | interest`), `version`; an exam attempt is one kind.
  - Add `requires: [{node_id, min_status}]` to nodes. Edges may point into other packs by fully
    qualified node ID. Load several packs at once into one graph and reject cycles.
  - `validate_pack.py` checks that every cross-pack edge resolves when the target pack is loaded.
- **Acceptance:** tests load two fixture packs with cross-pack prerequisites; a cycle is rejected;
  existing single-pack behaviour and node IDs are unchanged.

#### T101 — Learner profile and consent
- **Requirements:** REQUIREMENTS section 9, NFR privacy, `HUMAN-DECISIONS.md` section 10.
- **Build:** a `LearnerProfile` {student_id, graduation_degree, subjects[], interests[], goals[],
  language, consents{}} store behind an interface, with endpoints to read, update and delete it.
  Collect only these fields. Deletion is part of `DELETE /students/{id}` (T80).
- **Acceptance:** tests for create, update, consent flags and deletion together with the ledger.

#### T102 — Placement diagnostic from graduation profile
- **Requirements:** REQUIREMENTS section 9 ("start from what the student knows").
- **Build:** a deterministic placement plan: from the profile's degree and subjects, choose which
  prerequisite nodes to check first, then run the existing diagnostic and teach-back loop on them.
  The profile only orders what is checked; nothing is marked verified without graded evidence.
- **Acceptance:** tests show two profiles get different placement orders, and no node becomes
  VERIFIED without a graded ledger event.

#### T103 — Goals and next-topic recommender
- **Requirements:** REQUIREMENTS section 9, section 2 rules 1 and 2 of this file.
- **Build:**
  - Goals generalise T84 job profiles: `{goal_id, kind: exam|job|interest, required[{node_id,
    min_status}]}`.
  - `recommend(student_id) -> [{node_id, kind: "new"|"strengthen", score, reasons[]}]` as pure
    code over the ledger, course graph, profile and revision schedule. Signals: prerequisites met,
    gap against goals, interest match, revision due (T70), later demand signals. Weights are
    content configuration, not code constants.
  - `GET /students/{id}/recommendations`. A model may phrase the reasons for speech; it never
    chooses or reorders topics.
  - Interests change order and examples only; verification rules are the same for everyone.
- **Acceptance:** tests show that a node with unmet prerequisites is never recommended as new, a
  due revision appears as "strengthen", identical inputs give identical rankings, and every item has
  at least one reason.

#### T104 — Signed portable ledger export
- **Requirements:** REQUIREMENTS section 9 and roadmap Phase 3, NFR privacy.
- **Build:** export the student's ledger projection with evidence references as a signed document
  the student owns and can share; include a verification endpoint and key rotation notes.
- **Acceptance:** tests show a tampered export fails verification and a deleted student's platform
  data is gone while a previously issued export still verifies.

---

## 6. Human tasks (owner and experts)

Use `HUMAN-DECISIONS.md` to collect answers, approvals and evidence for the gates below and the
open questions in section 10. Do not mark a human task done until its required review or decision
has been recorded.

| ID | Task | Delivers to | Blocks |
|---|---|---|---|
| H1 | Choose the exam attempt and the one or two chapters. Supply the official sources: Ind AS 115 text, Ind AS 37 onerous-contract paragraphs, ICAI study material chapter(s), RTPs, MTPs and past papers. Confirm what may be committed and start the ICAI licence conversation. | `content/packs/ind_as_115/sources/` | Real corpus (T20 onward runs on the fixture until then) |
| H2 | Read Claude's review report for the concept map, resolve `needs_expert` items, check the random sample, and record the release sign-off with `record_audit.py` (D1, D6). | `reviews.json` | Strict mode; final eval expectations |
| H3 | Supply official worked illustrations with published solutions for each calculator; triage `needs_expert` task items; confirm the task set and grading defaults. | `tests/skills/reference_cases/`, `HUMAN-DECISIONS.md` section 7 | T51 reference tests, strict mode |
| H4 | Spot-check the Claude-reviewed eval cases and practice mapping. | eval case files, `practice_map.json` | T33 and T71 sign-off |
| H5 | Sign off the retrieval threshold from the calibration output. | `.env` / manifest | Strict boundary guard |
| H6 | Owner acceptance of the MVP: run the checklist in `HUMAN-DECISIONS.md` section 3. | `HUMAN-DECISIONS.md` | Milestone M10, any pilot |

---

## 7. Execution waves and critical path

Tasks in the same wave can run in parallel. A later wave starts when its tasks' dependencies are
done.

| Wave | Tasks |
|---|---|
| 1 | T00 → T01 → T02 (one agent, in order) |
| 2 | T10, T60, T82 |
| 3 | T11, T20 |
| 4 | T21 |
| 5 | T22, T50 |
| 6 | T30, T51, T23 |
| 7 | T31, T32, T83 |
| 8 | T40, T33, T61, T84 |
| 9 | T41, T52 |
| 10 | T42, T62 |
| 11 | T43, T53, T80 |
| 12 | T54, T63, T70, T81, T92, T85 |
| 13 | T64, T71, T90, T86, T66 |
| 14 | T65, then T91 |
| 15 (post-MVP, after H6) | T100, T101, T104, then T102, T103 |

**Critical path:** T00 → T01 → T02 → T10 → T20 → T21 → T22 → T30 → T31 → T40 → T41 → T42 →
T53 → T54 → T90 → T91.

**Serialised file:** `tutor/state_machine.py` is changed by T40, T41, T42, T53, T70 and T71. The
dependencies already force them into that order. Do not start one of them in parallel with another.

---

## 8. Traceability matrix

| Requirement | Tasks |
|---|---|
| FR-1 Voice-to-voice interface | baseline, T60, T63, T65, T91 |
| FR-2 Hierarchical knowledge tree | T10, T11, T23, H2 |
| FR-3 Grading (extract and map) | T30, T32, T33 |
| FR-4 Deepest missing node selection | baseline, T31, T70, T84 |
| FR-5 Adaptive tutor voice | T40, T41, T43 |
| FR-6 Teach-back | T40, T41 |
| FR-7 Mastery ledger | T31, T80 |
| FR-8 Mastery dashboard | T61, T62 |
| FR-9 Voice verification (mock) | T82 |
| FR-10 Syllabus content and retrieval | T10, T20, T21, T22, T83, H1 |
| FR-11 Syllabus boundary guard | T42, T43, H5 |
| FR-12 Skills | T50, T51, T52, T53, T54, T63, T64, T23, H3 |
| FR-13 Mastery, revision, practice | T53, T61, T64, T70, T71 |
| FR-14 Student flags and community review | T85, T86, T66 |
| NFR Flow owned by code | T40, T42, T53 (rules 1–2) |
| NFR Auditability | T31, T32 |
| NFR Determinism | T30, T32, T51 |
| NFR Accuracy and review | T11, T23, H2, H3, H6 |
| NFR Traceability | T31, T54 |
| NFR Latency and efficiency | T30, T91 |
| NFR Distraction-free | T61–T64 (rule 10) |
| NFR Portability | baseline speech interfaces, T82 |
| NFR Maintainability | T10, T83 |
| NFR Privacy | T80, T81 |
| AC1 Session, omission and misconception | T33, T90 |
| AC2 Claims, omission, misconception, citations | T30, T31, T33, T61, T90 |
| AC3 Socratic follow-up, then cited explanation | T40, T41, T90 |
| AC4 Confident wrong teach-back | T33, T41, T90 |
| AC5 Task with partial credit and routing | T52, T53, T63, T90 |
| AC6 Skill unlock and remaining tasks | T54, T64, T90 |
| AC7 Repeatable grading and answer keys | T32, T51, T90 |
| AC8 Out-of-syllabus question | T42, T90 |
| AC9 Flag escalation and correction | T85, T86 |
| D1 Grounded AI review | T11, T23, H2, H3, H4, H6 |
| D2 Personalised learning beyond exams | T100, T101, T102, T103, T104 |
| D5 Code review checkpoint | `tools/task_runner.py` (built) |
| D6 Claude and humans review, never Ollama | T11, T23, H2, H4 |
| D7 Student flags | T85, T86, T66 |

---

## 9. Code vs requirements disagreements (raised at planning time)

| # | Where | Disagreement | Resolution |
|---|---|---|---|
| 1 | `README.md` "Why there is no RAG" | Says retrieval makes grading non-deterministic; FR-10/11 require retrieval and citations. | Grading uses node-linked passages only (rule 6). Update README in T92. |
| 2 | `state_machine.py` `_introduce()` | Explains the node directly; FR-5 requires a probe first. | T40. |
| 3 | `models.py` `NodeVerdict`, `LedgerEvent` | No citations or source refs; FR-3/FR-7 need them. | T30, T31. |
| 4 | `curriculum/ind_as_115.json` | No review status; FR-2 requires grounded review before use. | T11, T23, H2. |
| 5 | `ledger.py` status names | `VERIFIED`/`GAP` vs the pitch's `MASTERED`/`GAP_IDENTIFIED`. | Keep internal names; map in the export (T31). |
| 6 | `grader.py` `_capture()` | Captures sit under `tests/` keyed by session only; deletion needs the student ID. | T32, T80. |
| 7 | `llm.py` `describe_grader()` | Reports the tutor model for Ollama. | T01. |
| 8 | `ledger.py` | A focused teach-back verdict can overwrite VERIFIED. | Keep as an explicit, evidence-linked downgrade; document it (T31). |
| 9 | `ind_as_115.cross_cutting.onerous` | Cites Ind AS 37, which is outside Ind AS 115. | Include those paragraphs in the corpus (H1) or the validator flags the node (T21). |
| 10 | `models.py` `Session.ledger` | Ledger is per session; FR-7 and FR-13 need a per-student ledger. | T31. |
| 11 | `state_machine.py` sentinel | The tutor LLM can move INSTRUCT→TEACH_BACK on any turn; NFR says the LLM never chooses the phase. | Code gates the sentinel (T40). |
| 12 | `integrity.py` | Code has `verify(student_id, audio)`; FR-9 says `verify(audio)`. | Keep `student_id`, since a real verifier needs to know whose voice to compare (T82). |

---

## 10. Open questions log

Agents append rows here. Humans answer them. Do not delete answered rows; mark them `answered`.

| # | Raised by | Task | Question | Status |
|---|---|---|---|---|
| Q1 | planning | H1 | Which exam attempt and which one or two chapters does the MVP cover? | answered 2026-09-27 (owner confirmed `HUMAN-DECISIONS.md` 5.1, 5.2): CA Final May 2027; Ind AS 115 plus Ind AS 37 paras 66–69 |
| Q2 | planning | H1 | May ICAI study material, RTP and MTP text be committed to this repository, or must it stay local? | answered 2026-09-27 (owner confirmed `HUMAN-DECISIONS.md` 5.4): ICAI material and extracts stay out of git; MCA text may be committed; ICAI licence before any pilot |
| Q3 | planning | T53 | Should a failed task downgrade the concept to PARTIAL (the planned default) or only schedule a review? | answered 2026-09-27 (owner confirmed `HUMAN-DECISIONS.md` 7.4): no automatic downgrade; review plus teach-back; arithmetic slips retry only |
| Q4 | planning | T80 | Authentication is needed before any non-local deployment, since student data endpoints are open. Who owns it and when? | answered 2026-09-27 (owner confirmed `HUMAN-DECISIONS.md` 11.1): localhost only until auth; OIDC provider such as Supabase Auth before any pilot; implementer to be named |
| Q5 | planning | H3 | Keep the default four tasks, or swap in time-and-materials billing or an onerous contract? | answered 2026-09-27 (owner confirmed `HUMAN-DECISIONS.md` 7.1): keep four tasks in one fictional IT services company |
| Q6 | owner | T11, T23 | Who reviews content? | answered 2026-09-27 (D1): grounded AI review against official sources, sampled expert audit; the owner does MVP acceptance. Refined by D6: the reviewer is Claude, never Ollama, with professional sign-off per release |
| Q7 | owner | M10 | Is Teach limited to exams? | answered 2026-09-27 (D2): no; personalised by interests and graduation knowledge, recommends next and weak topics |
| Q8 | planning | T23 | Which reviewer models go in `REVIEW_MODELS`? | superseded 2026-09-27 by D6: the reviewer is Claude (session or API); `REVIEW_MODELS` is replaced by `REVIEWER` |
| Q9 | planning | T100 | Which course comes second: Advanced Auditing or a graduation-level bridge course? | answered 2026-09-27 (owner confirmed `HUMAN-DECISIONS.md` section 10): Advanced Auditing is the second course |
| Q10 | owner | T85 | Confirm the community-check thresholds after the first 10 flags (confirmations, majority, closing rules). | recommended in `HUMAN-DECISIONS.md` section 12; awaiting owner |
