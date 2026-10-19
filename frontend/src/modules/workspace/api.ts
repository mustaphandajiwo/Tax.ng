// Typed client for the workspace module (backend/taxng/modules/workspace/routes.py).
import type { CalcResult } from "../../api";
import { http, qs } from "../../http";

export type Role = "owner" | "preparer" | "reviewer" | "read_only";
export type ReturnStatus = "draft" | "submitted_for_review" | "changes_requested" | "approved" | "filed_sandbox" | "filed";
export type SubmissionStatus = "prepared" | "submitting" | "acknowledged" | "rejected" | "failed" | "reconciled";

export interface OrgListItem {
  id: string;
  name: string;
  entity_type: string;
  state: string | null;
  role: Role;
}

export type Facts = Record<string, string | number | boolean>;

export interface Verification {
  id: string;
  id_type: string;
  id_masked: string;
  result: string;
  mode: string;
  checked_at: string;
}

export interface Org {
  id: string;
  name: string;
  entity_type: string;
  tin: string | null;
  cac_number: string | null;
  state: string | null;
  facts: Facts;
  role: Role;
  created_at: string;
  verifications: Verification[];
}

export interface Member {
  user_id: string;
  email: string;
  name: string;
  role: Role;
  created_at: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: Role;
  created_at?: string;
  expires_at: string;
}

export interface Reconciliation {
  liability: string;
  remitted: string;
  difference: string;
  status: "nothing_due" | "unpaid" | "underpaid" | "paid" | "overpaid";
  flag: string | null;
}

export interface CalendarItem {
  id: string;
  tax: string;
  title: string;
  frequency: string;
  period: string;
  due_date: string;
  provision: string;
  evidence: string[];
  applies_because: string;
  review_status: string;
  status: "not_started" | "in_preparation" | "submitted_for_review" | "approved" | "filed" | "paid";
  return_id: string | null;
  return_status: ReturnStatus | null;
  sandbox_acknowledged: boolean;
  payment: Reconciliation | null;
  suggested_return_type: string | null;
  overdue: boolean;
}

export interface Calendar {
  available: boolean;
  notice: string | null;
  year: number;
  items: CalendarItem[];
}

export interface ReturnSummary {
  id: string;
  return_type: string;
  period: string;
  title: string;
  status: ReturnStatus;
  obligation_id: string | null;
  obligation_period: string | null;
  due_date: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  filed_reference: string | null;
  totals: Record<string, string | number>;
}

export interface ReturnTypeSpec {
  id: string;
  label: string;
  tax: string;
  frequency: "monthly" | "annual";
  authority: string;
  kinds: string[];
  details: string[];
  inputs: string[];
  max_lines: number | null;
}

export interface Line {
  id: string;
  position: number;
  kind: string;
  details: Record<string, string>;
  inputs: Record<string, unknown>;
  result: CalcResult;
  rules_version: string;
  calculator: string;
  updated_by: string;
  updated_at: string;
}

export interface Payment {
  id: string;
  receipt_reference: string;
  amount: string;
  paid_on: string;
  channel: string;
  file_id: string | null;
  recorded_by: string;
  created_at: string;
}

export interface Submission {
  id: string;
  return_id: string;
  idempotency_key: string;
  status: SubmissionStatus;
  adapter: string;
  mode: string;
  document_hash: string;
  ack_reference: string | null;
  ack_verified: boolean;
  message: string;
  created_at: string;
  updated_at: string;
  reconciled_at: string | null;
  reconcile_note: string | null;
  sandbox: boolean;
  counts_as_filed: boolean;
  return_title?: string;
  return_status?: ReturnStatus;
  replayed?: boolean;
}

export interface FilingInfo {
  kind: string;
  name: string;
  mode: string;
  authorised: boolean;
  available: boolean;
  description: string;
  needs: string | null;
}

export interface ReturnDetail extends ReturnSummary {
  spec: ReturnTypeSpec;
  lines: Line[];
  events: { action: string; comment: string; at: string; actor_id: string; actor_email: string | null }[];
  documents: { id: string; name: string; content_type: string; size: number; category: string; linked_at: string }[];
  payments: Payment[];
  reconciliation: Reconciliation;
  submissions: Submission[];
  submitted_by: string | null;
  approved_by: string | null;
  approval_hash: string | null;
  locked: boolean;
  filing: FilingInfo;
  permissions: {
    edit: boolean;
    submit: boolean;
    review: boolean;
    review_block: string | null;
    reopen: boolean;
    export: boolean;
    file: boolean;
    record_payment: boolean;
    link_documents: boolean;
  };
}

export interface FileRecord {
  id: string;
  name: string;
  content_type: string;
  size: number;
  category: string;
  created_at: string;
}

export interface AuditItem {
  seq: number;
  at: string;
  action: string;
  entity: string;
  entity_id: string | null;
  actor: string | null;
  data: Record<string, unknown>;
  hash: string;
}

export interface OrgSummary {
  org: { id: string; name: string; entity_type: string; state: string | null; tin_masked: string | null };
  facts: Facts;
  open_returns: Record<string, number>;
  upcoming_obligations: { id: string; tax: string; title: string; period: string; due_date: string; status: string; return_id: string | null }[];
  calendar_available: boolean;
  calendar_notice: string | null;
}

const o = (orgId: string) => `/api/orgs/${encodeURIComponent(orgId)}`;
const r = (orgId: string, returnId: string) => `${o(orgId)}/returns/${encodeURIComponent(returnId)}`;

export const ws = {
  orgs: () => http.get<{ items: OrgListItem[] }>("/api/orgs"),
  createOrg: (body: Record<string, string>) => http.post<Org>("/api/orgs", body),
  org: (orgId: string) => http.get<Org>(o(orgId)),
  updateOrg: (orgId: string, body: Record<string, string>) => http.put<Org>(o(orgId), body),
  updateFacts: (orgId: string, facts: Facts) => http.put<Org>(`${o(orgId)}/facts`, facts),
  verify: (orgId: string, idType: "tin" | "cac") => http.post<Verification>(`${o(orgId)}/verify`, { id_type: idType }),
  summary: (orgId: string) => http.get<OrgSummary>(`${o(orgId)}/summary`),

  members: (orgId: string) => http.get<{ items: Member[] }>(`${o(orgId)}/members`),
  changeRole: (orgId: string, userId: string, role: Role) => http.put<{ items: Member[] }>(`${o(orgId)}/members/${userId}`, { role }),
  removeMember: (orgId: string, userId: string) => http.del<{ status: string }>(`${o(orgId)}/members/${userId}`),
  invitations: (orgId: string) => http.get<{ items: Invitation[] }>(`${o(orgId)}/invitations`),
  invite: (orgId: string, email: string, role: Role) => http.post<Invitation>(`${o(orgId)}/invitations`, { email, role }),
  revokeInvitation: (orgId: string, id: string) => http.del<{ status: string }>(`${o(orgId)}/invitations/${id}`),
  acceptInvitation: (token: string) => http.post<{ org_id: string; name: string; role: Role }>("/api/invitations/accept", { token }),

  calendar: (orgId: string, year: number) => http.get<Calendar>(`${o(orgId)}/calendar${qs({ year })}`),

  returnTypes: () => http.get<{ items: ReturnTypeSpec[]; channels: string[] }>("/api/workspace/return-types"),
  returns: (orgId: string) => http.get<{ items: ReturnSummary[] }>(`${o(orgId)}/returns`),
  createReturn: (orgId: string, body: Record<string, string>) => http.post<ReturnSummary>(`${o(orgId)}/returns`, body),
  returnDetail: (orgId: string, returnId: string) => http.get<ReturnDetail>(r(orgId, returnId)),
  addLine: (orgId: string, returnId: string, body: LineBody) => http.post<{ id: string; result: CalcResult }>(`${r(orgId, returnId)}/lines`, body),
  updateLine: (orgId: string, returnId: string, lineId: string, body: LineBody) =>
    http.put<{ id: string; result: CalcResult }>(`${r(orgId, returnId)}/lines/${lineId}`, body),
  deleteLine: (orgId: string, returnId: string, lineId: string) => http.del<{ status: string }>(`${r(orgId, returnId)}/lines/${lineId}`),
  submit: (orgId: string, returnId: string, comment: string) => http.post<ReturnDetail>(`${r(orgId, returnId)}/submit`, { comment }),
  approve: (orgId: string, returnId: string, comment: string) => http.post<ReturnDetail>(`${r(orgId, returnId)}/approve`, { comment }),
  requestChanges: (orgId: string, returnId: string, comment: string) => http.post<ReturnDetail>(`${r(orgId, returnId)}/request-changes`, { comment }),
  reopen: (orgId: string, returnId: string, reason: string) => http.post<ReturnDetail>(`${r(orgId, returnId)}/reopen`, { reason }),
  exportUrl: (orgId: string, returnId: string, format: "json" | "csv") => `${r(orgId, returnId)}/export${qs({ format })}`,

  linkDocument: (orgId: string, returnId: string, fileId: string) => http.post<{ status: string }>(`${r(orgId, returnId)}/documents`, { file_id: fileId }),
  unlinkDocument: (orgId: string, returnId: string, fileId: string) => http.del<{ status: string }>(`${r(orgId, returnId)}/documents/${fileId}`),
  documentLinks: (orgId: string) => http.get<{ links: Record<string, { return_id: string; title: string }[]> }>(`${o(orgId)}/document-links`),
  files: (orgId: string) => http.get<{ items: FileRecord[] }>(`/api/files${qs({ org_id: orgId })}`),
  upload: (orgId: string, body: { name: string; content_type: string; data_base64: string; category: string }) =>
    http.post<FileRecord>("/api/files", { ...body, org_id: orgId }),
  fileLink: (fileId: string) => http.post<{ url: string; expires: string }>(`/api/files/${fileId}/link`),
  deleteFile: (fileId: string) => http.del<{ status: string }>(`/api/files/${fileId}`),

  filingStatus: () => http.get<Pick<FilingInfo, "mode" | "authorised" | "available" | "description" | "needs">>("/api/filing/status"),
  file: (orgId: string, returnId: string, idempotencyKey: string) =>
    http.post<Submission>(`${r(orgId, returnId)}/file`, { idempotency_key: idempotencyKey }),
  submissions: (orgId: string) => http.get<{ items: Submission[]; filing: FilingInfo }>(`${o(orgId)}/submissions`),
  reconcile: (orgId: string, submissionId: string, note: string) => http.post<Submission>(`${o(orgId)}/submissions/${submissionId}/reconcile`, { note }),

  payments: (orgId: string) =>
    http.get<{ items: { return_id: string; title: string; status: ReturnStatus; payments: Payment[]; reconciliation: Reconciliation }[] }>(`${o(orgId)}/payments`),
  recordPayment: (orgId: string, returnId: string, body: Record<string, string>) =>
    http.post<{ payment: Payment; reconciliation: Reconciliation }>(`${r(orgId, returnId)}/payments`, body),
  voidPayment: (orgId: string, paymentId: string) => http.del<{ status: string }>(`${o(orgId)}/payments/${paymentId}`),

  audit: (orgId: string) => http.get<{ items: AuditItem[] }>(`${o(orgId)}/audit`),
};

export interface LineBody {
  kind: string;
  details: Record<string, string>;
  inputs: Record<string, string | boolean>;
}

/** Downloads an export with the session cookie (GET needs no CSRF header). */
export async function downloadExport(url: string, fallbackName: string): Promise<void> {
  const res = await fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "taxng" } });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { message?: string };
    throw new Error(body.message ?? `Export failed (${res.status})`);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  a.click();
  URL.revokeObjectURL(href);
}

export const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  submitted_for_review: "Submitted for review",
  changes_requested: "Changes requested",
  approved: "Approved",
  filed_sandbox: "Sandbox acknowledgement (not filed)",
  filed: "Filed",
  not_started: "Not started",
  in_preparation: "In preparation",
  paid: "Paid",
  prepared: "Prepared",
  submitting: "Submitting",
  acknowledged: "Acknowledged",
  rejected: "Rejected",
  failed: "Failed",
  reconciled: "Reconciled",
  nothing_due: "Nothing due",
  unpaid: "Unpaid",
  underpaid: "Underpaid",
  overpaid: "Overpaid",
};

export const STATUS_TONE: Record<string, "ok" | "warn" | "bad" | "muted" | ""> = {
  draft: "muted",
  not_started: "muted",
  in_preparation: "",
  submitted_for_review: "warn",
  changes_requested: "bad",
  approved: "ok",
  filed_sandbox: "warn",
  filed: "ok",
  paid: "ok",
  acknowledged: "ok",
  reconciled: "ok",
  rejected: "bad",
  failed: "bad",
  prepared: "muted",
  submitting: "warn",
  nothing_due: "muted",
  unpaid: "bad",
  underpaid: "bad",
  overpaid: "warn",
};

export const ROLE_LABEL: Record<Role, string> = { owner: "Owner", preparer: "Preparer", reviewer: "Reviewer", read_only: "Read only" };
