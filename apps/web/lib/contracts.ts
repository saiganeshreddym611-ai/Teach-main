export type Phase = "DIAGNOSTIC" | "INSTRUCT" | "TEACH_BACK" | "COMPLETE" | "TASK" | "REVIEW";
export type NodeStatus = "NOT_MENTIONED" | "GAP" | "PARTIAL" | "VERIFIED";

export interface ReviewClaim {
  claim: string;
  verdict: "supported" | "contradicted" | "not_found";
  passage_id: string | null;
  quote: string;
  quote_verified: boolean;
}

export interface Reviewer {
  mode: "session" | "claude-api";
  model: string;
}

export interface ReviewMeta {
  status: "draft" | "claude_reviewed" | "needs_expert" | "signed_off";
  content_sha256: string;
  reviewer: Reviewer | null;
  reviewed_at: string | null;
  claims: ReviewClaim[];
  report_id: string | null;
  signed_off_by: string | null;
  signed_off_at: string | null;
  notes: string;
}

export interface SourceDoc {
  doc_id: string;
  doc_code: string;
  title: string;
  short_name: string;
  doc_type: "standard" | "study_material" | "rtp" | "mtp" | "past_paper" | "amendment";
  issuer: string;
  authority_rank: number;
  attempt: string;
  version: string;
  path: string;
  sha256: string;
  license_note: string;
}

export interface Passage {
  passage_id: string;
  doc_id: string;
  doc_type: SourceDoc["doc_type"];
  paper: string;
  chapter: string;
  section: string;
  locator: string;
  attempt: string;
  version: string;
  page: number | null;
  text: string;
  sha256: string;
  supersedes: string[];
}

export interface Citation {
  passage_id: string;
  label: string;
  doc_id: string;
}

export interface ScoredPassage {
  passage: Passage;
  score: number;
  confidence: number;
}

export type ClaimJudgment =
  | "ACCURATE"
  | "INACCURATE"
  | "MISCONCEPTION"
  | "UNSUPPORTED"
  | "OFF_SYLLABUS";

export interface Claim {
  claim_id: string;
  quote: string;
  node_id: string | null;
  judgment: ClaimJudgment;
  passage_ids: string[];
}

export interface NodeVerdictV2 {
  node_id: string;
  status: NodeStatus;
  confidence: number;
  evidence: string;
  rubric_items_met: number[];
  misconception_ids: number[];
  passage_ids: string[];
  citation_origin: "model" | "node_link";
}

export interface GraderOutput {
  claims: Claim[];
  verdicts: NodeVerdictV2[];
  summary: string;
}

export interface Omission {
  node_id: string;
  citations: string[];
}

export interface LedgerEvent {
  kind: "concept";
  id: string;
  student_id: string;
  session_id: string | null;
  node_id: string;
  status: NodeStatus;
  confidence: number;
  evidence: string;
  evidence_turn_id: string;
  passage_ids: string[];
  grader_call_id: string | null;
  content_version: string | null;
  source: "diagnostic" | "probe" | "teach_back" | "task" | "review" | "practice";
  phase: Phase;
  ts: string;
}

export interface TaskAttemptEvent {
  kind: "task";
  id: string;
  student_id: string;
  session_id: string;
  skill_id: string;
  task_id: string;
  template_version: string;
  variant_seed: number;
  answer_key_sha256: string;
  score: number;
  passed: boolean;
  item_results: Array<{
    rubric_id: string;
    score: number;
    node_id: string | null;
    passage_ids: string[];
  }>;
  evidence_turn_id: string;
  grader_call_id: string | null;
  ts: string;
}

export interface ParamSpec {
  type: "money" | "percent" | "date" | "int" | "choice" | "name";
  min: number | null;
  max: number | null;
  step: number | null;
  choices: string[];
}

export interface SkillDef {
  skill_id: string;
  title: string;
  description: string;
  task_ids: string[];
  unlock_rule: "all_tasks_passed";
}

export interface TaskTemplate {
  task_id: string;
  skill_id: string;
  title: string;
  description: string;
  template_version: string;
  parameters: Record<string, ParamSpec>;
  rubric: Array<{
    rubric_id: string;
    description: string;
    node_id: string;
    passage_ids: string[];
  }>;
  brief: Record<string, unknown>;
  review_status: "draft" | "claude_reviewed" | "needs_expert" | "signed_off";
}
