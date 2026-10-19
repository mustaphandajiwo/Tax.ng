// Typed client for the publishing module (backend/taxng/modules/publishing/routes.py).
// Amounts arrive as integer kobo plus a decimal string ("amount"); never do arithmetic on them.
import { http, qs } from "../../http";

export type ArticleType = "commentary" | "news" | "opinion" | "submission" | "sponsored";
export type Section = "nigeria" | "africa" | "global";
export type ArticleState =
  | "draft"
  | "submitted"
  | "screening"
  | "revision_requested"
  | "fact_legal_review"
  | "approved"
  | "scheduled"
  | "published"
  | "corrected"
  | "withdrawn"
  | "rejected";

export interface Citation {
  text: string;
  url: string;
}

export interface Sponsor {
  name: string;
  funding_relationship: string;
}

export interface Labels {
  badge: string;
  sponsored: boolean;
  label: string | null;
  sponsor: Sponsor | null;
}

export interface ArticleCard extends Labels {
  id: string;
  slug: string;
  title: string;
  summary: string;
  article_type: ArticleType;
  section: Section | null;
  author_name: string;
  affiliation: string;
  published_at: string | null;
  corrected: boolean;
  url: string;
}

export interface Correction {
  version: number;
  note: string;
  created_at: string;
}

export interface ArticlePage extends Partial<ArticleCard> {
  slug: string;
  title: string;
  state: ArticleState;
  tombstone: boolean;
  body?: string;
  citations?: Citation[];
  author_credentials?: string;
  jurisdiction?: string;
  conflicts?: string;
  ai_disclosure?: string;
  version?: number;
  header_label?: string | null;
  withdrawn_at?: string;
  withdrawn_reason?: string;
  corrections: Correction[];
  meta: { json_ld?: Record<string, unknown>; open_graph?: Record<string, string>; robots?: string };
}

export interface NewsEntry {
  id: string;
  date: string;
  section: Section;
  headline: string;
  standfirst: string;
  source_name: string;
  source_url: string | null;
  sample: boolean;
  url: string | null;
  sponsored: boolean;
  label: string | null;
}

export interface SearchHit {
  id: string;
  kind: "article" | "provision" | "guide";
  title: string;
  url: string;
  summary?: string;
  badge?: string;
  sponsored: boolean;
  label: string | null;
}

export interface Audience {
  subscribers: number;
  threshold: number;
  open: boolean;
}

export interface Policy {
  terms_version: string;
  labels: Record<string, string>;
  rate_card: { id: string; name: string; description: string; price: string }[];
  placement_policy: string[];
  disclosure_rules: string[];
  rejection_and_refund: string[];
  slots: { id: string; label: string }[];
  audience: Audience;
}

export interface SubmissionFields {
  title: string;
  summary: string;
  body: string;
  author_name: string;
  author_credentials: string;
  affiliation: string;
  citations: Citation[];
  jurisdiction: string;
  rights_warranty: boolean;
  conflicts: string;
  ai_disclosure: string;
  sponsorship_declaration: "none" | "paid" | "in_kind";
  section?: Section | null;
  article_type?: ArticleType;
}

export interface Disclosure {
  sponsor_name: string;
  funding_relationship: string;
  label: "Sponsored" | "Paid Partnership";
  arcon_required: number;
  arcon_reference: string | null;
  sponsorship_id: string | null;
}

export interface Submission extends SubmissionFields {
  id: string;
  slug: string;
  state: ArticleState;
  article_type: ArticleType;
  badge: string;
  feedback: string;
  version: number;
  legal_signoff_by: string | null;
  sponsorship_id: string | null;
  scheduled_for: string | null;
  published_at: string | null;
  updated_at: string;
  revisions: { version: number; reason: string; title: string; created_at: string }[];
  history: { action: string; from_state: string; to_state: string; actor_role: string; note: string; created_at: string }[];
  corrections: Correction[];
  disclosure: Disclosure | null;
  publish_blockers: string[];
  labels: Labels;
  allowed_actions: string[];
}

export interface MySubmission {
  id: string;
  slug: string;
  title: string;
  state: ArticleState;
  badge: string;
  feedback: string;
  updated_at: string;
  version: number;
}

export interface QueueItem {
  id: string;
  title: string;
  state: ArticleState;
  badge: string;
  sponsored: boolean;
  legal_signed_off: boolean;
  author_name: string;
  updated_at: string;
}

export interface Complaint {
  id: string;
  kind: string;
  details: string;
  status: "received" | "investigating" | "resolved" | "rejected";
  resolution: string;
  created_at: string;
  contact_email: string | null;
  article_title: string | null;
}

export interface EditionItemRef {
  kind: "article" | "news";
  id: string;
}

export interface Edition {
  id: string;
  newsletter: "nigerian_tax_brief" | "global_tax_watch";
  newsletter_name: string;
  title: string;
  intro: string;
  items: EditionItemRef[];
  sponsorship_id: string | null;
  sponsor: { label: string; sponsor: string; funding_relationship: string } | null;
  state: "draft" | "fact_check" | "fact_checked" | "approved" | "scheduled" | "sent" | "archived";
  scheduled_for: string | null;
  sent_at: string | null;
  sent_count: number;
  send_blockers: string[];
}

export interface RenderedEdition {
  subject: string;
  newsletter_name: string;
  items: { kind: string; id: string; title: string; summary: string; url: string | null; badge: string; sponsored: boolean; label: string | null; source_name?: string; sample?: boolean }[];
  sponsor: { label: string; sponsor: string; funding_relationship: string } | null;
  ad: Ad | null;
  text: string;
}

export interface ArchivedEdition extends RenderedEdition {
  id: string;
  title: string;
  intro: string;
  sent_at: string;
}

export interface SponsorshipOrder {
  id: string;
  sponsor_name: string;
  funding_relationship: string;
  placement: "sponsored_article" | "newsletter_sponsor";
  label: "Sponsored" | "Paid Partnership";
  arcon_required: boolean;
  arcon_reference: string | null;
  amount_kobo: number;
  amount: string;
  status: "open" | "rejected" | "cancelled" | "fulfilled";
  payment_status: "unpaid" | "pending" | "paid" | "refund_due" | "refunded";
  rejection_reason: string | null;
  articles: { id: string; title: string; state: string; slug: string }[];
  editions: { id: string; title: string; state: string }[];
}

export interface Creative {
  id: string;
  headline: string;
  body: string;
  link_url: string;
  review_status: "pending" | "approved" | "rejected";
  review_note: string;
  impressions: number;
  clicks: number;
}

export interface Campaign {
  id: string;
  advertiser: string;
  starts_on: string;
  ends_on: string;
  slots: string[];
  amount: string;
  status: "draft" | "active" | "paused" | "ended" | "rejected";
  payment_status: string;
  creatives: Creative[];
  impressions?: number;
  clicks?: number;
}

export interface Ad {
  creative_id: string;
  headline: string;
  body: string;
  link_url: string;
  advertiser: string;
  label: string;
  image_url: string | null;
}

export interface CheckoutResult {
  billing_available: boolean;
  checkout: { checkout_id: string; url: string; mode: string } | null;
  mode?: string;
  message?: string;
}

export interface StaffDashboard {
  role: string;
  articles_by_state: Record<string, number>;
  awaiting_legal_signoff: number;
  creatives_pending_review: number;
  open_complaints: number;
  editions_in_progress: number;
  audience: Audience;
}

const P = "/api/publishing";

export const pub = {
  // public
  policy: () => http.get<Policy>(`${P}/policy`),
  articles: (q: { type?: string; section?: string } = {}) => http.get<{ items: ArticleCard[] }>(`${P}/articles${qs(q)}`),
  article: (slug: string) => http.get<ArticlePage>(`${P}/articles/${encodeURIComponent(slug)}`),
  news: (section: Section) => http.get<{ items: NewsEntry[] }>(`${P}/news${qs({ section })}`),
  search: (q: string) => http.get<{ items: SearchHit[] }>(`${P}/search${qs({ q })}`),
  archive: () => http.get<{ items: { id: string; newsletter_name: string; title: string; intro: string; sent_at: string; sponsored: boolean }[] }>(`${P}/newsletter/archive`),
  archived: (id: string) => http.get<ArchivedEdition>(`${P}/newsletter/archive/${encodeURIComponent(id)}`),
  complain: (body: { kind: string; details: string; article_slug?: string; contact_email?: string }) =>
    http.post<{ id: string; status: string; tracking_token: string }>(`${P}/complaints`, body),
  complaintStatus: (id: string, token: string) => http.get<{ status: string; resolution: string; updated_at: string }>(`${P}/complaints/${id}/status${qs({ token })}`),
  unsubscribe: (email: string, token: string) => http.post<{ status: string }>("/api/newsletter/unsubscribe", { email, token }),
  // contributor
  mine: () => http.get<{ items: MySubmission[] }>(`${P}/submissions`),
  create: (body: Partial<SubmissionFields>) => http.post<Submission>(`${P}/submissions`, body),
  get: (id: string) => http.get<Submission>(`${P}/submissions/${id}`),
  save: (id: string, body: Partial<SubmissionFields>) => http.post<Submission>(`${P}/submissions/${id}`, body),
  act: (id: string, action: string, body: Record<string, unknown> = {}) => http.post<Submission>(`${P}/submissions/${id}/transition/${action}`, body),
  classify: (id: string, body: { article_type?: string; section?: string | null }) => http.post<Submission>(`${P}/submissions/${id}/classify`, body),
  disclose: (id: string, body: Record<string, unknown>) => http.post<Submission>(`${P}/submissions/${id}/disclosure`, body),
  // staff
  dashboard: () => http.get<StaffDashboard>(`${P}/dashboard`),
  queue: (state?: string) => http.get<{ items: QueueItem[] }>(`${P}/queue${qs({ state })}`),
  runScheduled: () => http.post<{ articles: { published: string[] }; editions: { sent: string[] } }>(`${P}/run-scheduled`),
  complaints: () => http.get<{ items: Complaint[] }>(`${P}/complaints`),
  handleComplaint: (id: string, body: { status: string; resolution?: string }) => http.post<Complaint>(`${P}/complaints/${id}`, body),
  editions: () => http.get<{ items: Edition[] }>(`${P}/editions`),
  createEdition: (body: Record<string, unknown>) => http.post<Edition>(`${P}/editions`, body),
  previewEdition: (id: string) => http.get<RenderedEdition>(`${P}/editions/${id}/preview`),
  editionAct: (id: string, action: string, body: Record<string, unknown> = {}) => http.post<Edition>(`${P}/editions/${id}/transition/${action}`, body),
  sponsorships: () => http.get<{ items: SponsorshipOrder[]; audience: Audience }>(`${P}/sponsorships`),
  createSponsorship: (body: Record<string, unknown>) => http.post<SponsorshipOrder>(`${P}/sponsorships`, body),
  updateSponsorship: (id: string, body: Record<string, unknown>) => http.post<SponsorshipOrder>(`${P}/sponsorships/${id}`, body),
  attach: (id: string, articleId: string) => http.post<SponsorshipOrder>(`${P}/sponsorships/${id}/attach`, { article_id: articleId }),
  checkout: (id: string) => http.post<CheckoutResult>(`${P}/sponsorships/${id}/checkout`),
  reject: (id: string, reason: string) => http.post<SponsorshipOrder>(`${P}/sponsorships/${id}/reject`, { reason }),
  refunded: (id: string) => http.post<{ payment_status: string }>(`${P}/sponsorships/${id}/refunded`),
  reports: () => http.get<{ audience: Audience; campaigns: Campaign[]; sponsorships: SponsorshipOrder[] }>(`${P}/reports`),
  // ads
  campaigns: () => http.get<{ items: Campaign[]; audience: Audience }>("/api/ads/campaigns"),
  createCampaign: (body: Record<string, unknown>) => http.post<Campaign>("/api/ads/campaigns", body),
  addCreative: (id: string, body: Record<string, unknown>) => http.post<Creative>(`/api/ads/campaigns/${id}/creatives`, body),
  campaignStatus: (id: string, status: string, reason = "") => http.post<Campaign>(`/api/ads/campaigns/${id}/status`, { status, reason }),
  campaignCheckout: (id: string) => http.post<CheckoutResult>(`/api/ads/campaigns/${id}/checkout`),
  review: (id: string, decision: "approved" | "rejected", note = "") => http.post<Creative>(`/api/ads/creatives/${id}/review`, { decision, note }),
  slot: (slot: string, page: string) => http.get<{ slot: string; ad: Ad | null; reason?: string }>(`/api/ads/slot/${slot}${qs({ page })}`),
  impression: (id: string) => http.post<{ status: string }>(`/api/ads/impression/${id}`),
  click: (id: string) => http.post<{ url: string }>(`/api/ads/click/${id}`),
};

export const RSS_URL = `${P}/rss.xml`;

export const STATE_LABEL: Record<string, string> = {
  draft: "Draft",
  submitted: "Submitted",
  screening: "Screening",
  revision_requested: "Revision requested",
  fact_legal_review: "Fact and legal review",
  approved: "Approved",
  scheduled: "Scheduled",
  published: "Published",
  corrected: "Corrected",
  withdrawn: "Withdrawn",
  rejected: "Rejected",
  fact_check: "Fact check",
  fact_checked: "Fact checked",
  sent: "Sent",
  archived: "Archived",
};

export const ACTION_LABEL: Record<string, string> = {
  submit: "Submit for review",
  screen: "Start screening",
  request_revision: "Request revision",
  send_to_review: "Send to fact and legal review",
  sign_off: "Sign off fact and legal review",
  approve: "Approve",
  reject: "Reject",
  schedule: "Schedule",
  publish: "Publish now",
  correct: "Publish a correction",
  withdraw: "Withdraw",
};

export function stateTone(state: string): string {
  if (["published", "corrected", "approved", "sent", "fact_checked", "resolved"].includes(state)) return "pill pill--ok";
  if (["revision_requested", "scheduled", "fact_check", "investigating", "pending"].includes(state)) return "pill pill--warn";
  if (["withdrawn", "rejected"].includes(state)) return "pill pill--bad";
  return "pill pill--muted";
}
