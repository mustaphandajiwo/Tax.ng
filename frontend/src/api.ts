// Typed client for the tax.ng API. Mirrors backend/taxng/api/handlers.py.
// Money values are decimal strings ("330000.00"); never parse them for arithmetic.
import { ApiError, request } from "./http";

export { ApiError };

export type Money = string;
export type ReviewStatus = "unverified" | "secondary_source" | "legal_approved";

export interface Step {
  label: string;
  amount: Money | null;
  note: string | null;
}

export interface BandRow {
  lower: Money;
  upper: Money | null;
  rate: string;
  taxable: Money;
  tax: Money;
}

export interface CalcResult {
  calculator: string;
  regime: string;
  period: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, string | boolean>;
  steps: Step[];
  bands: BandRow[];
  assumptions: string[];
  warnings: string[];
  citations: string[];
  parameters_used: Record<string, unknown>;
  review_status: ReviewStatus;
  rules_version: string;
  engine_version: string;
}

export interface CompareResult {
  calculator: "pit-compare";
  old: CalcResult;
  new: CalcResult;
  difference: { annual_change: Money; monthly_change: Money; direction: "lower" | "higher" | "same" };
}

export interface ParameterCard {
  name: string;
  description: string;
  unit: string | null;
  review_status: ReviewStatus;
  reference: string | null;
  in_force: boolean;
  value?: string | string[] | boolean;
  scale?: { threshold: string; rate: string }[];
}

export interface Provision {
  id: string;
  instrument: string;
  section: string;
  title: string;
  tax: string;
  effective_from: string;
  effective_to: string | null;
  in_force: boolean;
  summary: string;
  review_status: ReviewStatus;
  parameters: ParameterCard[];
}

export interface GuideSummary {
  id: string;
  title: string;
  summary: string;
  applies_from: string;
  calculator: string | null;
  languages: string[];
}

export interface Guide extends GuideSummary {
  body: string[];
  provisions: { id: string; title: string }[];
  figures: ParameterCard[];
}

export interface NewsItem {
  id: string;
  date: string;
  section: string;
  headline: string;
  standfirst: string;
  source_name: string;
  source_url: string;
  sample: boolean;
}

export interface Citation {
  id: string;
  title: string;
  instrument: string;
  section: string;
  review_status: ReviewStatus;
}

export interface AskResult {
  answer: string;
  blocked: boolean;
  confidence: "high" | "medium" | "low";
  escalate: boolean;
  tax_year: number;
  citations: Citation[];
  tool_calls: { name: string; arguments: Record<string, unknown> }[];
  calculation: CalcResult | null;
  guard: { citations_ok: boolean; figures_ok: boolean; problems: string[] };
  notices: string[];
  disclaimer: string;
}

export interface Meta {
  owner: string;
  rules_version: string;
  engine_version: string;
  nav: NavItem[];
  footer_nav: NavItem[];
  app_nav: NavItem[];
  demo_mode: boolean;
  pit_deductions: { id: string; label: string }[];
  vat_categories: string[];
  wht_payment_types: { id: string; label: string; recipients: string[] }[];
  consent_text: string;
}

export interface NavItem {
  id: string;
  label: string;
  path: string;
  phase: number;
  placement: "header" | "footer" | "app";
  requires_adapter: string | null;
  staff_only: boolean;
}

export const api = {
  meta: () => request<Meta>("GET", "/api/meta"),
  calculate: (calculator: string, payload: Record<string, unknown>) =>
    request<CalcResult>("POST", `/api/calculate/${calculator}`, payload),
  compare: (payload: Record<string, unknown>) => request<CompareResult>("POST", "/api/calculate/pit-compare", payload),
  laws: (tax?: string) => request<{ on: string; items: Provision[] }>("GET", `/api/laws${tax ? `?tax=${tax}` : ""}`),
  law: (id: string) => request<Provision>("GET", `/api/laws/${encodeURIComponent(id)}`),
  guides: () => request<{ items: GuideSummary[] }>("GET", "/api/guides"),
  guide: (id: string) => request<Guide>("GET", `/api/guides/${encodeURIComponent(id)}`),
  news: () => request<{ items: NewsItem[] }>("GET", "/api/news"),
  search: (q: string) =>
    request<{ items: { id: string; kind: string; title: string }[] }>("GET", `/api/search?q=${encodeURIComponent(q)}`),
  ask: (question: string) => request<AskResult>("POST", "/api/ask", { question }),
  subscribe: (email: string, consent: boolean) =>
    request<{ status: string }>("POST", "/api/newsletter/subscribe", { email, consent }),
  event: (name: string, props: Record<string, string> = {}) =>
    request<unknown>("POST", "/api/events", { name, props }).catch(() => undefined),
};
