// The More tab: every destination that is not a tab, grouped the way a
// person looks for it. Replaces the website header menu and footer.
import type { Meta, NavItem } from "../api";
import { Icon } from "../components/icons";
import { Link } from "../router";

const TAB_PATHS = new Set(["/", "/calculators", "/ask", "/laws", "/more"]);

const GROUPS: { title: string; ids: string[] }[] = [
  { title: "Learn", ids: ["reform", "news", "insights", "academy"] },
  { title: "Get help", ids: ["health-check", "advisers", "whatsapp"] },
  { title: "For business", ids: ["business", "developers", "advertise", "contribute"] },
  { title: "Settings", ids: ["newsletter", "languages"] },
  { title: "About", ids: ["about"] },
];

const ICONS: Record<string, string> = {
  reform: "reform",
  news: "news",
  insights: "insight",
  academy: "academy",
  "health-check": "health",
  advisers: "adviser",
  whatsapp: "chat",
  business: "briefcase",
  developers: "code",
  advertise: "megaphone",
  contribute: "pen",
  newsletter: "mail",
  languages: "globe",
  about: "info",
};

function Row({ item }: { item: NavItem }) {
  return (
    <li>
      <Link to={item.path} className="row">
        <span className="row__icon">
          <Icon name={ICONS[item.id] ?? "info"} />
        </span>
        <span className="row__label">{item.label}</span>
        <span className="row__chevron">
          <Icon name="chevron" size={18} />
        </span>
      </Link>
    </li>
  );
}

export function More({ meta }: { meta: Meta }) {
  const items = [...meta.nav, ...meta.footer_nav].filter((n) => !TAB_PATHS.has(n.path));
  const byId = new Map(items.map((n) => [n.id, n]));
  const placed = new Set(GROUPS.flatMap((g) => g.ids));
  const other = items.filter((n) => !placed.has(n.id));
  const groups = [...GROUPS.map((g) => ({ title: g.title, items: g.ids.flatMap((id) => byId.get(id) ?? []) })), { title: "Other", items: other }].filter(
    (g) => g.items.length > 0,
  );

  return (
    <>
      <h1>More</h1>

      <a className="signin-card" href="/app/">
        <span className="row__icon">
          <Icon name="user" />
        </span>
        <span>
          <strong>Sign in</strong>
          <span className="muted small"> Save calculations, track deadlines and file returns.</span>
        </span>
        <span className="row__chevron">
          <Icon name="chevron" size={18} />
        </span>
      </a>

      {groups.map((g) => (
        <section key={g.title} className="group">
          <h2 className="group__title">{g.title}</h2>
          <ul className="rows">
            {g.items.map((n) => (
              <Row key={n.id} item={n} />
            ))}
          </ul>
        </section>
      ))}

      <div className="legal small muted">
        <p>
          © 2026 {meta.owner}. tax.ng is owned and licensed by {meta.owner}. tax.ng is not a tax authority and does not
          act for one. Content is general information, not tax advice.
        </p>
        <p>
          Rules {meta.rules_version} · engine {meta.engine_version}
        </p>
      </div>
    </>
  );
}
