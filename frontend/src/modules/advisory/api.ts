// Typed client for the advisory module (backend/taxng/modules/advisory/routes.py, booking_routes.py).
import { http, qs } from "../../http";
import type { Report } from "../compliance/api";

export interface Verification {
  status: "verified" | "expired" | "not_verified";
  checked_at: string | null;
  expires_at: string | null;
  mode: "sandbox" | "production" | null;
  registers: string[];
}

export interface PublicAdviser {
  id: string;
  name: string;
  firm: string;
  state: string;
  location: string;
  bio: string;
  specialisms: string[];
  memberships: { register: string; number: string }[];
  verification: Verification;
  sponsored?: boolean;
}

export interface MyListing {
  id: string;
  name: string;
  firm: string;
  state: string;
  location: string;
  bio: string;
  status: "pending" | "approved" | "rejected" | "suspended";
  review_note: string | null;
  citn_number: string | null;
  ican_number: string | null;
  specialisms: string[];
  verification: Verification & { checks: { register: string; number_masked: string; result: string; mode: string; checked_at: string }[] };
  user_id?: string;
}

export interface AdvisoryMeta {
  specialisms: { id: string; label: string }[];
  states: string[];
  practitioner_notice: string;
  consent_text: Record<string, string>;
  engagement_scopes: { id: string; label: string }[];
  register_mode: string;
}

export interface Engagement {
  id: string;
  booking_id: string;
  status: "active" | "ended";
  created_at: string;
  ended_at: string | null;
  terms_notice: string;
  consent: { id: string; scope: string[]; granted_at: string } | null;
  adviser?: { id: string; name: string; firm: string };
  topic?: string;
}

export interface Booking {
  id: string;
  status: "requested" | "accepted" | "declined" | "cancelled";
  topic: string;
  message: string;
  preferred_date: string | null;
  created_at: string;
  decided_at: string | null;
  decision_note: string | null;
  adviser: { id: string; name: string; firm: string };
  intake_fields: string[];
  intake?: { fields: string[]; data: Record<string, unknown> };
  engagement: Engagement | null;
  practitioner_notice: string;
}

export interface IntakeOption {
  id: string;
  label: string;
  value: unknown;
}

export interface UserConsent {
  granted: boolean;
  granted_at: string | null;
  text: string;
}

const enc = encodeURIComponent;

export const advisoryApi = {
  meta: () => http.get<AdvisoryMeta>("/api/advisory/meta"),
  directory: (specialism?: string, state?: string) =>
    http.get<{ items: PublicAdviser[]; sponsored: PublicAdviser[]; sponsored_label: string; practitioner_notice: string }>(
      `/api/advisory/directory${qs({ specialism, state })}`,
    ),
  adviser: (id: string) => http.get<PublicAdviser & { practitioner_notice: string }>(`/api/advisory/directory/${enc(id)}`),
  // the caller's listing
  apply: (body: Record<string, unknown>) => http.post<MyListing>("/api/advisory/advisers", body),
  mine: () => http.get<MyListing>("/api/advisory/advisers/me"),
  updateMine: (body: Record<string, unknown>) => http.put<MyListing>("/api/advisory/advisers/me", body),
  reverify: () => http.post<Verification>("/api/advisory/advisers/me/verify"),
  placements: () => http.get<{ items: { id: string; status: string; amount_kobo: number; starts_at: string | null; ends_at: string | null; mode: string | null }[] }>("/api/advisory/advisers/me/placements"),
  buyPlacement: () => http.post<{ available: boolean; checkout: { checkout_id: string; url: string; mode: string }; price_status: string }>("/api/advisory/advisers/me/placements"),
  // client
  intakeOptions: () => http.get<{ items: IntakeOption[] }>("/api/advisory/intake-options"),
  book: (body: Record<string, unknown>) => http.post<Booking>("/api/advisory/bookings", body),
  bookings: () => http.get<{ items: Booking[] }>("/api/advisory/bookings"),
  cancel: (id: string) => http.post<Booking>(`/api/advisory/bookings/${enc(id)}/cancel`),
  engagements: () => http.get<{ items: Engagement[] }>("/api/advisory/engagements"),
  grant: (id: string, scope: string[]) => http.post<Engagement>(`/api/advisory/engagements/${enc(id)}/consent`, { consent: true, scope }),
  revoke: (id: string) => http.del<Engagement>(`/api/advisory/engagements/${enc(id)}/consent`),
  end: (id: string) => http.post<Engagement>(`/api/advisory/engagements/${enc(id)}/end`),
  accessLog: (id: string) => http.get<{ items: { at: string; action: string; by: string; detail: Record<string, unknown> }[] }>(`/api/advisory/engagements/${enc(id)}/access-log`),
  consents: () => http.get<Record<"marketing" | "findings_matching", UserConsent>>("/api/advisory/consents"),
  setConsent: (kind: string, granted: boolean) => http.post<Record<"marketing" | "findings_matching", UserConsent>>(`/api/advisory/consents/${enc(kind)}`, { granted }),
  suggestions: () => http.get<{ consent_required: boolean; items: PublicAdviser[]; specialisms: string[] }>("/api/advisory/suggestions"),
  // adviser portal
  requests: () => http.get<{ items: Booking[] }>("/api/advisory/adviser/bookings"),
  request: (id: string) => http.get<Booking>(`/api/advisory/adviser/bookings/${enc(id)}`),
  decide: (id: string, decision: "accept" | "decline", note = "") => http.post<Booking>(`/api/advisory/adviser/bookings/${enc(id)}/decision`, { decision, note }),
  adviserEngagements: () => http.get<{ items: Engagement[] }>("/api/advisory/adviser/engagements"),
  clientReport: (id: string) => http.get<{ engagement_id: string; report: Report | null; consent: { id: string; granted_at: string } }>(`/api/advisory/adviser/engagements/${enc(id)}/report`),
  // staff
  staffList: (status?: string) => http.get<{ items: MyListing[] }>(`/api/advisory/admin/advisers${qs({ status })}`),
  staffDecide: (id: string, decision: string, note = "") => http.post<MyListing>(`/api/advisory/admin/advisers/${enc(id)}/decision`, { decision, note }),
};

export function verificationText(v: Verification): string {
  if (v.status === "not_verified") return "Not verified";
  const when = v.checked_at ? v.checked_at.slice(0, 10) : "";
  if (v.status === "expired") return `Verification expired (last checked ${when})`;
  const registers = v.registers.join(" and ");
  return v.mode === "sandbox" ? `${registers} membership checked ${when} (sandbox check, not a real register look-up)` : `${registers} membership verified ${when}`;
}
