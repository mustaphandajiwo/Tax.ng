// App shell: a top bar with a back button on nested screens, a bottom tab
// bar on phones and a sidebar on wider screens. The website header, menu and
// footer are gone; secondary destinations live on the More screen.
import { type ReactNode } from "react";
import type { Meta } from "../api";
import { Link } from "../router";
import { Icon } from "./icons";

export const TABS = [
  { id: "home", label: "Home", path: "/", icon: "home" },
  { id: "calculate", label: "Calculate", path: "/calculators", icon: "calc" },
  { id: "ask", label: "Ask AI", path: "/ask", icon: "ask" },
  { id: "laws", label: "Laws", path: "/laws", icon: "laws" },
  { id: "more", label: "More", path: "/more", icon: "more" },
] as const;

// Screens reached from More count as More for the active-tab highlight.
function activeTab(path: string): string {
  if (path === "/") return "home";
  const root = `/${path.split("/")[1] ?? ""}`;
  const tab = TABS.find((t) => t.path !== "/" && t.path === root);
  return tab ? tab.id : "more";
}

// Parent screen for the back button, with the label the user knows it by.
function parentOf(path: string, meta?: Meta): { to: string; label: string } | null {
  const parts = path.split("/").filter(Boolean);
  if (parts.length === 0) return null;
  const tabRoot = TABS.find((t) => t.path === `/${parts[0]}`);
  if (parts.length === 1) {
    // A top-level screen that is not a tab goes back to More.
    return tabRoot ? null : { to: "/more", label: "More" };
  }
  const to = `/${parts[0]}`;
  const navItem = [...(meta?.nav ?? []), ...(meta?.footer_nav ?? [])].find((n) => n.path === to);
  const label = tabRoot?.label ?? navItem?.label ?? "Back";
  return { to, label };
}

export function Layout({ meta, path, children }: { meta?: Meta; path: string; children: ReactNode }) {
  const current = activeTab(path);
  const parent = parentOf(path, meta);
  return (
    <div className="shell">
      <a className="skip" href="#main">
        Skip to content
      </a>

      <aside className="rail" aria-label="Main">
        <Link to="/" className="brand rail__brand" aria-label="tax.ng home">
          tax<span>.ng</span>
        </Link>
        <nav className="rail__nav">
          {TABS.map((t) => (
            <Link key={t.id} to={t.path} className="rail__item" aria-current={current === t.id ? "page" : undefined}>
              <Icon name={t.icon} />
              <span>{t.label}</span>
            </Link>
          ))}
        </nav>
        <a className="rail__signin" href="/app/">
          <Icon name="user" />
          <span>Sign in</span>
        </a>
      </aside>

      <div className="shell__body">
        <header className={`topbar${parent ? "" : " topbar--root"}`}>
          {parent ? (
            <Link to={parent.to} className="topbar__back">
              <Icon name="back" />
              <span>{parent.label}</span>
            </Link>
          ) : (
            <Link to="/" className="brand topbar__brand" aria-label="tax.ng home">
              tax<span>.ng</span>
            </Link>
          )}
          <a className="topbar__account" href="/app/" aria-label="Sign in">
            <Icon name="user" />
          </a>
        </header>

        <div className="demo-bar" role="note">
          Demo build. Rules come from secondary sources and are pending legal sign-off. Not for real tax decisions.
        </div>

        <main id="main" className="screen" key={path}>
          {children}
        </main>
      </div>

      <nav className="tabbar" aria-label="Main">
        {TABS.map((t) => (
          <Link key={t.id} to={t.path} className="tabbar__item" aria-current={current === t.id ? "page" : undefined}>
            <Icon name={t.icon} />
            <span>{t.label}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}
