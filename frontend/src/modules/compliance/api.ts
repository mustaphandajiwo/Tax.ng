// Typed client for the compliance module (backend/taxng/modules/compliance/routes.py).
// Every figure and finding comes from the API; the frontend does no tax logic.
import { http, qs } from "../../http";

export type Facts = Record<string, string | number | boolean>;
export type QuestionStatus = "answered" | "unknown" | "not_applicable" | "unanswered";

export interface Question {
  id: string;
  kind: "fact" | "evidence";
  text: string;
  type: "choice" | "state" | "bool" | "count" | "money" | "evidence";
  status: QuestionStatus;
  answer: string | number | boolean | null;
  fact?: string;
  options?: { value: string; label: string }[];
  allow_unknown?: boolean;
  obligation?: string;
  obligation_title?: string;
  dimension?: string;
  allow_na?: boolean;
}

export interface Contradiction {
  id: string;
  message: string;
  questions: string[];
}

export interface ObligationSummary {
  id: string;
  tax: string;
  title: string;
  frequency: "monthly" | "annual";
  provision: string;
  applies_because: string;
  review_status: string;
  due_rule: string;
  due_date_review_status: string;
  note: string | null;
  periods: string[];
  due_dates: string[];
}

export interface Undetermined {
  id: string;
  title: string;
  unknown_facts: string[];
  periods: string[];
}

export interface CheckState {
  check: { id: string; year: number; status: "in_progress" | "completed"; created_at: string; updated_at: string; completed_at: string | null };
  facts: Facts;
  questions: Question[];
  not_applicable: string[];
  contradictions: Contradiction[];
  progress: { shown: number; answered: number; unknown: number; not_applicable: number; unanswered: number };
  obligations: ObligationSummary[];
  undetermined: Undetermined[];
}

export interface CheckListItem {
  id: string;
  year: number;
  status: "in_progress" | "completed";
  created_at: string;
  completed_at: string | null;
}

export interface ReportLink {
  kind: "guide" | "calculator" | "adviser";
  label: string;
  path: string;
  specialism?: string;
}

export interface Finding {
  id: string;
  dimension: string;
  obligation: string;
  obligation_title: string;
  tax: string;
  status: "gap" | "insufficient_evidence";
  severity: "high" | "medium" | "low" | null;
  review_recommended: boolean;
  title: string;
  question: string | null;
  answer: string | null;
  why_it_matters: string;
  next_step: string;
  evidence_missing: string[];
  provision: string;
  links: ReportLink[];
}

export interface Cell {
  status: "gap" | "insufficient_evidence" | "ok" | "not_applicable" | "not_assessed";
  severity: "high" | "medium" | "low" | null;
}

export interface MatrixRow {
  id: string;
  tax: string;
  title: string;
  frequency: string;
  provision: string;
  status: "applies" | "undetermined";
  applies_because: string;
  review_status: string;
  due_rule?: string;
  due_date_review_status?: string;
  next_due_date?: string;
  periods: string[];
  note?: string | null;
  cells: Record<string, Cell>;
}

export interface DimensionSummary {
  id: string;
  label: string;
  status: "gaps_found" | "insufficient_evidence" | "no_gaps_found" | "not_assessed";
  gaps: { high: number; medium: number; low: number };
  insufficient_evidence: number;
  ok: number;
}

export interface Report {
  check_id: string;
  year: number;
  generated_at: string;
  as_of: string;
  statement: string;
  review_note: string;
  facts: Facts;
  obligations: MatrixRow[];
  dimensions: DimensionSummary[];
  findings: Finding[];
  missing_evidence: { obligation: string; obligation_title: string; documents: string[] }[];
  next_steps: { text: string; priority: string; obligation?: string; links: ReportLink[] }[];
  citations: { id: string; title: string; instrument: string; section: string; review_status: string }[];
  rules_version: string;
}

export const complianceApi = {
  profile: () => http.get<{ facts: Facts; updated_at: string | null; contradictions: Contradiction[] }>("/api/compliance/profile"),
  deleteProfile: () => http.del<{ status: string }>("/api/compliance/profile"),
  checks: () => http.get<{ items: CheckListItem[] }>("/api/compliance/checks"),
  start: (year: number) => http.post<CheckState>("/api/compliance/checks", { year }),
  check: (id: string) => http.get<CheckState>(`/api/compliance/checks/${encodeURIComponent(id)}`),
  answer: (id: string, answers: Record<string, unknown>) =>
    http.put<CheckState>(`/api/compliance/checks/${encodeURIComponent(id)}/answers`, { answers }),
  complete: (id: string) => http.post<Report>(`/api/compliance/checks/${encodeURIComponent(id)}/complete`),
  report: (id: string) => http.get<Report>(`/api/compliance/checks/${encodeURIComponent(id)}/report`),
  remove: (id: string) => http.del<{ status: string }>(`/api/compliance/checks/${encodeURIComponent(id)}`),
  downloadUrl: (id: string) => `/api/compliance/checks/${encodeURIComponent(id)}/report${qs({ download: 1 })}`,
};

export const DIMENSION_LABEL: Record<string, string> = {
  obligation_coverage: "Obligation coverage",
  timeliness: "Timeliness",
  documentation: "Documentation",
  reporting_accuracy: "Reporting accuracy",
  exposure_materiality: "Exposure materiality",
  evidence_confidence: "Evidence confidence",
};
