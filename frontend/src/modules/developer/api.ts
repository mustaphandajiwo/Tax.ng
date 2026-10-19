// Typed client for the developer module (backend/taxng/modules/developer/routes.py).
import { http } from "../../http";

export interface Catalogue {
  scopes: { id: string; description: string }[];
  events: { id: string; description: string }[];
  retry_schedule_seconds: number[];
  erp_profiles: { id: string; label: string; status: string; mapping_status: string; live_sync: string | null; columns: Record<string, string> }[];
  openapi_url: string;
  modes: Record<string, string>;
}

export interface ApiKey {
  id: string;
  org_id: string;
  name: string;
  prefix: string;
  scopes: string[];
  rate_per_minute: number;
  mode: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  token?: string;
  token_notice?: string;
}

export interface Endpoint {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  secret_hint: string;
  created_at: string;
  disabled_at: string | null;
  secret?: string;
  secret_notice?: string;
}

export interface Delivery {
  id: string;
  endpoint_id: string;
  endpoint_url: string | null;
  event_id: string;
  event: string;
  status: string;
  attempts: number;
  retry_schedule_seconds: number[];
  last_attempt_at: string | null;
  headers: Record<string, string>;
  body: string;
  mode: string;
  created_at: string;
}

export interface ImportItem {
  index: number;
  external_id: string | null;
  invoice_number: string | null;
  status: "validated" | "created" | "duplicate" | "failed";
  invoice_id?: string;
  errors?: Record<string, string>;
}

export interface ImportResult {
  import_id: string;
  profile: string;
  rows: number;
  source: string;
  counts: { created: number; validated: number; duplicate: number; failed: number };
  items: ImportItem[];
  mode: string;
}

export interface SourceReport {
  source: string;
  imported: number;
  submitted: number;
  accepted: number;
  rejected: number;
  by_status: Record<string, number>;
  mismatched_totals: { invoice_id: string; external_id: string; invoice_number: string; differences: Record<string, { declared: string; computed: string }> }[];
  invalid: { invoice_id: string; external_id: string; invoice_number: string; errors: Record<string, string> }[];
  mode: string;
}

export interface Reconciliation {
  sources: SourceReport[];
  imports: { id: string; profile: string; source: string; filename: string | null; rows: number; counts: ImportResult["counts"]; created_at: string }[];
  mode: string;
}

export interface OpenApiDoc {
  info: { title: string; version: string; description: string };
  paths: Record<string, Record<string, { summary: string; "x-required-scope"?: string | null; security?: unknown[] }>>;
  "x-error-codes": Record<string, string>;
}

const org = (orgId: string) => `/api/orgs/${encodeURIComponent(orgId)}`;

export const developerApi = {
  catalogue: () => http.get<Catalogue>("/api/developer/catalogue"),
  openapi: () => http.get<OpenApiDoc>("/api/v1/openapi.json"),
  keys: (orgId: string) => http.get<{ items: ApiKey[] }>(`${org(orgId)}/api-keys`),
  createKey: (orgId: string, name: string, scopes: string[], rate_per_minute: number) =>
    http.post<ApiKey>(`${org(orgId)}/api-keys`, { name, scopes, rate_per_minute }),
  revokeKey: (orgId: string, id: string) => http.post<ApiKey>(`${org(orgId)}/api-keys/${id}/revoke`),
  endpoints: (orgId: string) => http.get<{ items: Endpoint[]; mode: string }>(`${org(orgId)}/webhooks`),
  addEndpoint: (orgId: string, url: string, events: string[]) => http.post<Endpoint>(`${org(orgId)}/webhooks`, { url, events }),
  disableEndpoint: (orgId: string, id: string) => http.post<Endpoint>(`${org(orgId)}/webhooks/${id}/disable`),
  deliveries: (orgId: string) => http.get<{ items: Delivery[]; mode: string }>(`${org(orgId)}/webhook-deliveries`),
  replay: (orgId: string, id: string) => http.post<Delivery>(`${org(orgId)}/webhook-deliveries/${id}/replay`),
  importFile: (orgId: string, body: { profile: string; format: string; filename?: string; data_base64?: string; content?: string }) =>
    http.post<ImportResult>(`${org(orgId)}/erp/import`, body),
  reconciliation: (orgId: string) => http.get<Reconciliation>(`${org(orgId)}/erp/reconciliation`),
};
