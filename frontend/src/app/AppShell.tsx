// Signed-in app (served at /app; app.tax.ng in production, ADR-06).
// No advertising or third-party scripts are ever loaded here.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, type Meta } from "../api";
import { Loading, Notice } from "../components/ui";
import { ApiError, http } from "../http";
import { appModules } from "../modules/registry";
import type { AppContext, AppRoute, Me } from "../modules/types";
import { Link, match, useRoute } from "../router";
import { Account, Dashboard, Staff } from "./core";
import { Login } from "./Login";

const ORG_KEY = "taxng.activeOrg";

function readOrg(): string | null {
  try {
    return window.localStorage.getItem(ORG_KEY);
  } catch {
    return null;
  }
}

function writeOrg(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(ORG_KEY, id);
    else window.localStorage.removeItem(ORG_KEY);
  } catch {
    /* storage unavailable: keep in memory only */
  }
}

const CORE_ROUTES: AppRoute[] = [
  ["/", (ctx) => <Dashboard ctx={ctx} />],
  ["/account", (ctx) => <Account ctx={ctx} />],
  ["/staff", (ctx) => <Staff ctx={ctx} />],
];
const ROUTES: AppRoute[] = [...CORE_ROUTES, ...appModules.flatMap((m) => m.routes)];

function render(path: string, base: Omit<AppContext, "params">): ReactNode {
  for (const [pattern, view] of ROUTES) {
    const params = match(pattern, path);
    if (params) return view({ ...base, params });
  }
  return (
    <>
      <h1>Page not found</h1>
      <Link to="/">Back to the dashboard</Link>
    </>
  );
}

export function AppShell() {
  const path = useRoute();
  const [meta, setMeta] = useState<Meta>();
  const [me, setMe] = useState<Me | null>();
  const [orgId, setOrgIdState] = useState<string | null>(readOrg);
  const [error, setError] = useState<string>();
  const [open, setOpen] = useState(false);

  const refreshMe = useCallback(async () => {
    try {
      setMe(await http.get<Me>("/api/me"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setMe(null);
      else setError("Could not load your account.");
    }
  }, []);

  useEffect(() => {
    api.meta().then(setMeta, () => setError("Could not reach tax.ng."));
    void refreshMe();
  }, [refreshMe]);

  const setOrgId = (id: string | null) => {
    setOrgIdState(id);
    writeOrg(id);
  };

  if (error) return <div className="wrap main"><Notice tone="error">{error}</Notice></div>;
  if (!meta || me === undefined) return <div className="wrap main"><Loading /></div>;
  if (me === null) return <Login meta={meta} onSignedIn={refreshMe} />;

  const org = me.organisations.find((o) => o.id === orgId) ?? null;
  const ctx = { me, meta, orgId: org ? org.id : null, org, setOrgId, refreshMe };
  const nav = meta.app_nav.filter((n) => !n.staff_only || me.staff_role !== "none");

  const signOut = async () => {
    await http.post("/api/auth/logout").catch(() => undefined);
    setOrgId(null);
    setMe(null);
  };

  return (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="app__top">
        <a href="/" className="brand" aria-label="tax.ng public site">
          tax<span>.ng</span>
        </a>
        <div className="app__org">
          <label htmlFor="org-switch" className="sr-only">
            Active organisation
          </label>
          <select id="org-switch" value={org?.id ?? ""} onChange={(e) => setOrgId(e.target.value || null)}>
            <option value="">Personal</option>
            {me.organisations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name} ({o.role.replace("_", " ")})
              </option>
            ))}
          </select>
        </div>
        <button type="button" className="menu-toggle" aria-expanded={open} aria-controls="app-nav" onClick={() => setOpen(!open)}>
          Menu
        </button>
      </header>
      <div className="app__body">
        <nav id="app-nav" className={`app__nav${open ? " app__nav--open" : ""}`} aria-label="App">
          {nav.map((n) => (
            <Link
              key={n.id}
              to={n.path}
              aria-current={(n.path === "/" ? path === "/" : path === n.path || path.startsWith(`${n.path}/`)) ? "page" : undefined}
              onClick={() => setOpen(false)}
            >
              {n.label}
            </Link>
          ))}
          <button type="button" className="btn btn--ghost app__signout" onClick={() => void signOut()}>
            Sign out
          </button>
          <p className="muted small">{me.email}</p>
        </nav>
        <main id="main" className="app__main">
          {meta.demo_mode && (
            <p className="demo-chip" role="note">
              Demo environment · integrations run in sandbox mode
            </p>
          )}
          {render(path, ctx)}
        </main>
      </div>
    </div>
  );
}
