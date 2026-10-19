// Typed client for the channels module (backend/taxng/modules/channels/routes.py).
import { http, qs } from "../../http";

export interface AdapterInfo {
  kind: string;
  name: string;
  mode: string;
  authorised: boolean;
  description: string;
}

export interface BotReply {
  status: "replied" | "duplicate" | "rate_limited";
  kind?: string;
  reply?: string | null;
  mode: string;
}

export interface WaLog {
  items: { sender: string; direction: "in" | "out"; kind: string; snippet: string; created_at: string }[];
  contacts: number;
  opted_out: number;
  retention_note: string;
  adapter: AdapterInfo;
}

export interface Language {
  lang: string;
  name: string;
  native_name: string;
  approved: number;
  total: number;
  status: "source" | "reviewed";
}

export interface LanguageInReview {
  lang: string;
  name: string;
  native_name: string;
  drafts: number;
  approved: number;
}

export interface Catalogue {
  lang: string;
  status: "source" | "reviewed";
  strings: Record<string, string>;
  fallback_keys: string[];
}

export interface Pending {
  id: string;
  key: string;
  text: string;
  submitted_by: string;
  submitted_at: string;
}

export interface StaffStrings {
  lang: string;
  name: string;
  note: string;
  items: { key: string; english: string; draft: string | null; approved: string | null; pending: Pending | null }[];
}

export interface GuideSubmission {
  id: string;
  guide_id: string;
  guide_title: string;
  english_summary: string;
  lang: string;
  summary: string;
  status: "submitted" | "approved" | "rejected";
  submitted_by: string;
  submitted_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export interface GuideTranslations {
  guide_id: string;
  english_summary: string;
  items: { lang: string; name: string; summary: string; approved_at: string | null; source: "content" | "review" }[];
}

const enc = encodeURIComponent;

export const channelsApi = {
  status: () => http.get<{ adapter: AdapterInfo; demo_available: boolean; retention_note: string }>("/api/channels/whatsapp/status"),
  demo: (phone: string, text: string) => http.post<BotReply>("/api/channels/whatsapp/demo", { phone, text }),
  log: () => http.get<WaLog>("/api/channels/whatsapp/log"),
  alert: (phone: string, text: string) => http.post<{ status: string; mode: string }>("/api/channels/whatsapp/alerts", { phone, text }),
  languages: () => http.get<{ default: string; languages: Language[]; in_review: LanguageInReview[] }>("/api/i18n"),
  catalogue: (lang: string) => http.get<Catalogue>(`/api/i18n/${enc(lang)}`),
  staffStrings: (lang: string) => http.get<StaffStrings>(`/api/channels/translations${qs({ lang })}`),
  submitString: (lang: string, key: string, text: string) => http.post<{ id: string }>("/api/channels/translations", { lang, key, text }),
  reviewString: (id: string, decision: "approve" | "reject", note = "") => http.post<{ status: string }>(`/api/channels/translations/${enc(id)}/${decision}`, { note }),
  guideQueue: (status?: string) => http.get<{ items: GuideSubmission[] }>(`/api/channels/guide-translations${qs({ status })}`),
  submitGuide: (guide_id: string, lang: string, summary: string) => http.post<{ id: string }>("/api/channels/guide-translations", { guide_id, lang, summary }),
  reviewGuide: (id: string, decision: "approve" | "reject", note = "") =>
    http.post<{ status: string }>(`/api/channels/guide-translations/${enc(id)}/${decision}`, { note }),
  guideTranslations: (guideId: string) => http.get<GuideTranslations>(`/api/channels/guide-translations/${enc(guideId)}`),
};
