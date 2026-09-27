export type Phase = "DIAGNOSTIC" | "INSTRUCT" | "TEACH_BACK" | "COMPLETE" | "TASK" | "REVIEW" | "PRACTICE";
export type NodeStatus = "NOT_MENTIONED" | "GAP" | "PARTIAL" | "VERIFIED";

export type Turn = {
  id: string;
  role: "student" | "tutor";
  text: string;
  phase: Phase;
  ts: string;
};

export type MasteryEntry = {
  node_id: string;
  title: string;
  level: 1 | 2 | 3;
  parent: string | null;
  status: NodeStatus;
  confidence: number | null;
};

export type Verdict = {
  node_id: string;
  status: NodeStatus;
  confidence: number;
  evidence: string;
};

export type GradeEvent = {
  verdicts: Verdict[];
  summary: string;
  claims?: ReviewClaim[];
  omissions?: Omission[];
};

export type DoneEvent = {
  phase: Phase;
  target_node: string | null;
  tutor_turn_id: string;
  student_turn_id: string;
  ledger_delta: LedgerEvent[];
  citations?: Citation[];
  grounding?: Passage[];
};

export type SessionView = {
  session_id: string;
  student_id: string;
  topic_id: string;
  phase: Phase;
  target_node: string | null;
  student_level_summary: string;
  mastery: MasteryEntry[];
  turns: Turn[];
  ledger: LedgerEvent[];
};

export type Sha256 = string;
export type ReviewStatus = "draft" | "claude_reviewed" | "needs_expert" | "signed_off";
export type DocType = "standard" | "study_material" | "rtp" | "mtp" | "past_paper" | "amendment";
export type ClaimVerdict = "supported" | "contradicted" | "not_found";
export type ParamType = "money" | "percent" | "date" | "int" | "choice" | "name";

export type ReviewerInfo = {
  mode: "session" | "claude-api";
  model?: string;
};

export type ReviewClaim = {
  claim: string;
  verdict: ClaimVerdict;
  passage_id?: string | null;
  quote?: string;
  quote_verified?: boolean;
};

export type ReviewMeta = {
  status?: ReviewStatus;
  content_sha256: Sha256;
  reviewer?: ReviewerInfo | null;
  claims?: ReviewClaim[];
  report_id?: string | null;
  signed_off_by?: string | null;
  signed_off_at?: string | null;
  notes?: string;
};

export type ReleaseSignoff = {
  pack_id: string;
  version: string;
  content_hash: Sha256;
  signed_off_by: string;
  signed_off_at: string;
  scope_note?: string;
};

export type SourceDoc = {
  doc_id: string;
  doc_code: string;
  title: string;
  short_name?: string;
  doc_type: DocType;
  issuer?: string;
  authority_rank: number;
  attempt?: string | null;
  version?: string;
  path: string;
  sha256?: string;
  license_note?: string;
};

export type Passage = {
  passage_id: string;
  doc_id: string;
  doc_type: DocType;
  paper?: string;
  chapter?: string;
  section?: string;
  locator: string;
  attempt?: string | null;
  version?: string;
  page?: number | null;
  text: string;
  sha256: Sha256;
  supersedes?: string[];
};

export type Citation = {
  passage_id: string;
  label: string;
  doc_id: string;
};

export type ScoredPassage = {
  passage: Passage;
  score: number;
  confidence?: number;
};

export type PackManifest = {
  pack_id: string;
  exam: string;
  paper: string;
  attempt: string;
  version: string;
  topics: string[];
  doc_codes?: Record<string, string>;
  out_of_scope_message?: string;
};

export type CorpusManifest = {
  built_from: Record<string, string>;
  chunk_count: number;
  corpus_sha256: Sha256;
};

export type ClaimJudgment =
  | "ACCURATE"
  | "INACCURATE"
  | "MISCONCEPTION"
  | "UNSUPPORTED"
  | "OFF_SYLLABUS";

export type Claim = {
  claim_id: string;
  quote: string;
  node_id?: string | null;
  judgment: ClaimJudgment;
  passage_ids?: string[];
};

export type NodeVerdictV2 = {
  node_id: string;
  status: NodeStatus;
  confidence: number;
  evidence?: string;
  rubric_items_met?: number[];
  misconception_ids?: number[];
  passage_ids?: string[];
  citation_origin?: "model" | "node_link";
};

export type GraderOutput = {
  claims?: Claim[];
  verdicts: NodeVerdictV2[];
  summary: string;
};

export type Omission = {
  node_id: string;
  citations?: Citation[];
};

export type LedgerSource =
  | "diagnostic"
  | "probe"
  | "teach_back"
  | "task"
  | "review"
  | "practice";

export type LedgerEvent = {
  kind?: "concept";
  id: string;
  student_id: string;
  node_id: string;
  status: NodeStatus;
  confidence: number;
  evidence_turn_id: string;
  phase: Phase;
  ts: string;
  session_id?: string | null;
  evidence?: string;
  passage_ids?: string[];
  grader_call_id?: string | null;
  content_version?: string | null;
  source?: LedgerSource | null;
};

export type RubricItemResult = {
  rubric_id: string;
  score: number;
  node_id?: string | null;
  passage_ids?: string[];
};

export type TaskAttemptEvent = {
  kind?: "task";
  id?: string;
  student_id: string;
  session_id: string;
  skill_id: string;
  task_id: string;
  template_version: string;
  variant_seed: number;
  answer_key_sha256: Sha256;
  score: number;
  passed: boolean;
  item_results?: RubricItemResult[];
  evidence_turn_id: string;
  grader_call_id?: string | null;
  ts?: string;
};

export type ParamSpec = {
  type: ParamType;
  min?: string | null;
  max?: string | null;
  step?: string | null;
  choices?: string[];
};

export type NumericCheck = {
  type: "numeric";
  field: string;
  tolerance?: string;
};

export type DiscrepancyCheck = {
  type: "discrepancy";
  discrepancy_id: string;
};

export type JudgementCheck = {
  type: "judgement";
};

export type RubricCheck = NumericCheck | DiscrepancyCheck | JudgementCheck;

export type RubricItem = {
  id: string;
  text: string;
  weight?: number;
  node_id: string;
  passage_ids?: string[];
  required?: boolean;
  check: RubricCheck;
};

export type PlantedDiscrepancy = {
  id: string;
  row_id: string;
  issue_type: string;
  node_id: string;
  passage_ids?: string[];
};

export type TaskDocument = {
  doc_id: string;
  title: string;
  columns: string[];
  rows: Array<Record<string, string>>;
};

export type TaskTemplate = {
  task_id: string;
  skill_id: string;
  title: string;
  kind: "calculation" | "discrepancy_hunt";
  node_ids: string[];
  company?: Record<string, string>;
  narrative_template: string;
  params?: Record<string, ParamSpec>;
  constraints?: string[];
  documents?: TaskDocument[];
  calculator: string;
  answer_fields: string[];
  rubric: RubricItem[];
  planted_discrepancies?: PlantedDiscrepancy[];
  model_answer_template?: string;
  pass_threshold: number;
  template_version: string;
};

export type TaskVariant = {
  task_id: string;
  seed: number;
  params: Record<string, string>;
  narrative: string;
  documents?: TaskDocument[];
  answer_key: Record<string, string>;
  answer_key_sha256: Sha256;
};

export type SkillDef = {
  skill_id: string;
  title: string;
  description?: string;
  task_ids: string[];
  unlock_rule?: "all_tasks_passed";
};

export type ContentInfo = {
  manifest: PackManifest;
  content_hash: Sha256;
  review_counts?: Record<string, Record<string, number>>;
};

export type PassageResponse = {
  passage: Passage;
  source: SourceDoc;
  citation: Citation;
};

export type VerifyRequest = {
  student_id: string;
  audio_b64: string;
};

export type VerifyResponse = {
  match: boolean;
  score: number;
  method: string;
};
