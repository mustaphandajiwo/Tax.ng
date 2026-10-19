// Typed client for the billing module (backend/taxng/modules/billing/routes.py).
// Commercial payments only: tax is never paid through tax.ng.
import { http, qs } from "../../http";

export interface Plan {
  id: string;
  name: string;
  category: string;
  scope: "org" | "user";
  interval: string;
  unit: string;
  price_kobo: number;
  currency: string;
  price_status: "placeholder" | "approved";
  price_label: string | null;
  features: string[];
  seats: boolean;
}

export interface Subscription {
  id: string;
  plan_id: string;
  category: string;
  org_id: string | null;
  quantity: number;
  status: "pending" | "active" | "cancelled" | "superseded";
  checkout_id: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  created_at: string;
  cancelled_at: string | null;
  plan: Plan | null;
  personal: boolean;
}

export interface Checkout {
  checkout_id: string;
  url: string;
  mode: string;
}

export interface Payment {
  id: string;
  checkout_id: string;
  purpose: string;
  reference_id: string;
  org_id: string | null;
  amount_kobo: number;
  currency: string;
  description: string;
  status: "pending" | "paid" | "failed";
  provider: string;
  mode: string;
  created_at: string;
  paid_at: string | null;
  receipt_id?: string | null;
}

export interface Receipt {
  id: string;
  number: string;
  payment_id: string;
  org_id: string | null;
  description: string;
  amount_kobo: number;
  currency: string;
  mode: string;
  issued_at: string;
  seller: string;
  billed_to: string | null;
  billed_to_tin: string | null;
  nature: string;
  sandbox_note: string | null;
}

export const billingApi = {
  plans: () => http.get<{ items: Plan[]; mode: string; note: string }>("/api/billing/plans"),
  subscriptions: (orgId: string | null) => http.get<{ items: Subscription[] }>(`/api/billing/subscriptions${qs({ org_id: orgId })}`),
  subscribe: (planId: string, orgId: string | null, quantity: number) =>
    http.post<{ subscription: Subscription; checkout: Checkout }>("/api/billing/subscriptions", { plan_id: planId, org_id: orgId, quantity }),
  cancel: (id: string) => http.post<Subscription>(`/api/billing/subscriptions/${id}/cancel`),
  payments: (orgId: string | null) => http.get<{ items: Payment[]; mode: string }>(`/api/billing/payments${qs({ org_id: orgId })}`),
  checkout: (id: string) => http.get<Payment>(`/api/billing/checkout/${id}`),
  complete: (id: string, outcome: "paid" | "failed") =>
    http.post<{ status: string; receipt_id: string | null; mode: string }>(`/api/billing/checkout/${id}/complete`, { outcome }),
  receipt: (id: string) => http.get<Receipt>(`/api/billing/receipts/${id}`),
};

/** Formats integer kobo as naira without floating-point arithmetic. */
export function koboToNaira(kobo: number): string {
  const whole = Math.trunc(kobo / 100);
  const frac = String(Math.abs(kobo % 100)).padStart(2, "0");
  return `₦${whole.toLocaleString("en-NG")}.${frac}`;
}
