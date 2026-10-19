// Contracts every feature module implements. See docs/MODULES.md.
import type { ReactNode } from "react";
import type { Meta } from "../api";

/** A public-site route: hash path pattern ("/advisers/:id") and its page. */
export type SiteRoute = [pattern: string, render: (params: Record<string, string>, meta: Meta) => ReactNode];

export interface SiteModule {
  id: string;
  routes: SiteRoute[];
}

export interface Membership {
  id: string;
  name: string;
  entity_type: string;
  role: "owner" | "preparer" | "reviewer" | "read_only";
}

export interface Me {
  id: string;
  email: string;
  name: string;
  staff_role: "none" | "editor" | "legal_reviewer" | "sales" | "support" | "admin";
  ai_account_access: boolean;
  memberships: Record<string, string>;
  organisations: Membership[];
}

/** Everything an app page needs: who is signed in, which organisation is active. */
export interface AppContext {
  me: Me;
  meta: Meta;
  orgId: string | null;
  org: Membership | null;
  setOrgId: (id: string | null) => void;
  refreshMe: () => Promise<void>;
  params: Record<string, string>;
}

export type AppRoute = [pattern: string, render: (ctx: AppContext) => ReactNode];

export interface AppModule {
  id: string;
  routes: AppRoute[];
  /** Optional cards for the dashboard home. */
  dashboard?: (ctx: AppContext) => ReactNode;
}
