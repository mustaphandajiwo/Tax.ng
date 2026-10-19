// Typed client for the e-invoicing module (backend/taxng/modules/einvoicing/routes.py).
import { http, qs } from "../../http";

export type InvoiceStatus = "draft" | "validated" | "submitted" | "accepted" | "rejected" | "cancelled";
export const STATUSES: InvoiceStatus[] = ["draft", "validated", "submitted", "accepted", "rejected", "cancelled"];
export type VatCategory = "standard" | "zero_rated" | "exempt";

export interface LineInput {
  description: string;
  quantity: string;
  unit_price: string;
  vat_category: VatCategory;
}

export interface InvoiceInput {
  invoice_number: string;
  issue_date: string;
  due_date?: string;
  buyer_name: string;
  buyer_tin: string;
  buyer_email?: string;
  notes?: string;
  lines: LineInput[];
}

export interface Line extends LineInput {
  vat_rate: string;
  net: string;
  vat: string;
  gross: string;
}

export interface Totals {
  net?: string;
  vat?: string;
  gross?: string;
}

export interface InvoiceEvent {
  seq: number;
  at: string;
  actor_id: string | null;
  event: string;
  from_status: string | null;
  to_status: string | null;
  data: Record<string, unknown>;
}

export interface Invoice {
  id: string;
  org_id: string;
  kind: "invoice" | "credit_note";
  original_invoice_id: string | null;
  invoice_number: string;
  status: InvoiceStatus;
  issue_date: string | null;
  due_date: string | null;
  buyer_name: string;
  buyer_tin: string;
  buyer_email: string | null;
  notes: string | null;
  input_lines: Partial<LineInput>[];
  lines: Line[];
  totals: Totals;
  declared_totals: Totals | null;
  errors: Record<string, string>;
  rules_version: string | null;
  source: string;
  external_id: string | null;
  submission_ref: string | null;
  irn: string | null;
  qr_payload: string | null;
  mode: string;
  rejection_reason: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  decided_at: string | null;
  events?: InvoiceEvent[];
}

export interface InvoiceList {
  items: Invoice[];
  counts: Record<InvoiceStatus, number>;
  mode: string;
}

export interface ExceptionItem {
  id: string;
  invoice_number: string;
  status: InvoiceStatus;
  kind: "rejected" | "failed";
  reason: string | null;
  buyer_name: string;
  totals: Totals;
  updated_at: string;
  mode: string;
}

export interface Submission {
  invoice: Invoice;
  mode: string;
  replayed: boolean;
}

export interface SyncResult {
  processed: number;
  items: { invoice_number: string; invoice_id: string; status: string; reason?: string | null; duplicate: boolean }[];
  mode: string;
}

const base = (orgId: string) => `/api/orgs/${encodeURIComponent(orgId)}`;

export const einvoicingApi = {
  list: (orgId: string, status?: string) => http.get<InvoiceList>(`${base(orgId)}/einvoices${qs({ status })}`),
  get: (orgId: string, id: string) => http.get<Invoice>(`${base(orgId)}/einvoices/${id}`),
  create: (orgId: string, body: InvoiceInput) => http.post<Invoice>(`${base(orgId)}/einvoices`, body),
  update: (orgId: string, id: string, body: InvoiceInput) => http.put<Invoice>(`${base(orgId)}/einvoices/${id}`, body),
  validate: (orgId: string, id: string) => http.post<Invoice>(`${base(orgId)}/einvoices/${id}/validate`),
  submit: (orgId: string, id: string, idempotencyKey: string) =>
    http.post<Submission>(`${base(orgId)}/einvoices/${id}/submit`, { idempotency_key: idempotencyKey }),
  retry: (orgId: string, id: string) => http.post<Submission>(`${base(orgId)}/einvoices/${id}/retry`),
  cancel: (orgId: string, id: string, reason: string) => http.post<Invoice>(`${base(orgId)}/einvoices/${id}/cancel`, { reason }),
  creditNote: (orgId: string, id: string, reason: string) => http.post<Invoice>(`${base(orgId)}/einvoices/${id}/credit-note`, { reason }),
  exceptions: (orgId: string) => http.get<{ items: ExceptionItem[]; mode: string }>(`${base(orgId)}/einvoicing/exceptions`),
  sync: (orgId: string) => http.post<SyncResult>(`${base(orgId)}/einvoicing/sync`),
  submitValidated: (orgId: string, source?: string) =>
    http.post<{ submitted: string[]; mode: string }>(`${base(orgId)}/einvoicing/submit-validated`, { source }),
};

export const STATUS_TONE: Record<InvoiceStatus, string> = {
  draft: "muted",
  validated: "warn",
  submitted: "warn",
  accepted: "ok",
  rejected: "bad",
  cancelled: "muted",
};

export const CATEGORY_LABEL: Record<VatCategory, string> = {
  standard: "Standard rated",
  zero_rated: "Zero rated",
  exempt: "Exempt",
};

export function modeLabel(mode: string): string {
  return mode === "sandbox" ? "Sandbox: not sent to NRS" : mode;
}
