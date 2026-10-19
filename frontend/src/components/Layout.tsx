import { useState, type ReactNode } from "react";
import type { Meta } from "../api";
import { Link } from "../router";

export function Layout({ meta, path, children }: { meta?: Meta; path: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const nav = meta?.nav ?? [];
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="header">
        <div className="wrap header__inner">
          <Link to="/" className="brand" aria-label="tax.ng home">
            tax<span>.ng</span>
          </Link>
          <button
            type="button"
            className="menu-toggle"
            aria-expanded={open}
            aria-controls="site-nav"
            onClick={() => setOpen(!open)}
          >
            Menu
          </button>
          <nav id="site-nav" className={`nav${open ? " nav--open" : ""}`} aria-label="Main">
            {nav.map((n) => (
              <Link
                key={n.id}
                to={n.path}
                aria-current={path === n.path || path.startsWith(`${n.path}/`) ? "page" : undefined}
                onClick={() => setOpen(false)}
              >
                {n.label}
              </Link>
            ))}
            <a className="nav__signin" href="/app/">
              Sign in
            </a>
          </nav>
        </div>
      </header>
      <div className="demo-bar" role="note">
        <div className="wrap">
          Demo build. Rules come from secondary sources and are pending legal sign-off. Not for real tax decisions.
        </div>
      </div>
      <main id="main" className="wrap main">
        {children}
      </main>
      <footer className="footer">
        <div className="wrap footer__inner">
          {meta && meta.footer_nav.length > 0 && (
            <nav className="footer__nav" aria-label="More">
              {meta.footer_nav.map((n) => (
                <Link key={n.id} to={n.path}>
                  {n.label}
                </Link>
              ))}
            </nav>
          )}
          <p>
            © 2026 {meta?.owner ?? "Astound Innovation Hub"}. tax.ng is owned and licensed by{" "}
            {meta?.owner ?? "Astound Innovation Hub"}.
          </p>
          <p>
            tax.ng is not a tax authority and does not act for one. Content is general information, not tax advice.
          </p>
          {meta && (
            <p className="muted small">
              Rules {meta.rules_version} · engine {meta.engine_version}
            </p>
          )}
        </div>
      </footer>
    </>
  );
}
