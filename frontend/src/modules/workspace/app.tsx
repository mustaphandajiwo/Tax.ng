// Signed-in app pages for the "workspace" module (PRD Phase 3 workspaces, Phase 4 filing).
import { Loading, useLoad } from "../../components/ui";
import { date } from "../../format";
import { Link } from "../../router";
import type { AppContext, AppModule } from "../types";
import { STATUS_LABEL, ws } from "./api";
import { AcceptInvitation, Audit, Documents, Filing, Members, Overview, Payments, Profile, WorkspaceList } from "./pages";
import { ReturnPage, ReturnsList } from "./returns";

function DashboardCard({ ctx }: { ctx: AppContext }) {
  const orgId = ctx.orgId;
  const summary = useLoad(() => (orgId ? ws.summary(orgId) : Promise.resolve(null)), [orgId]);
  if (!orgId)
    return (
      <Link to="/workspaces" className="card card--link">
        <h2>Business workspaces</h2>
        <p>Returns, approvals, documents and payment records for your organisation.</p>
      </Link>
    );
  if (!summary.data) return <div className="card"><Loading error={summary.error} /></div>;
  const s = summary.data;
  const open = Object.entries(s.open_returns);
  return (
    <section className="card">
      <h2>
        <Link to={`/workspaces/${orgId}`}>{s.org.name}</Link>
      </h2>
      {open.length ? (
        <p className="small">{open.map(([status, n]) => `${n} ${STATUS_LABEL[status]?.toLowerCase() ?? status}`).join(", ")}</p>
      ) : (
        <p className="small muted">No open returns.</p>
      )}
      {s.upcoming_obligations.length ? (
        <ul className="list list--tight">
          {s.upcoming_obligations.slice(0, 3).map((o) => (
            <li key={`${o.id}-${o.period}`}>
              <strong>{o.title}</strong>
              <span>
                Due {date(o.due_date)} · {STATUS_LABEL[o.status] ?? o.status}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="small muted">{s.calendar_notice ?? "No upcoming obligations."}</p>
      )}
    </section>
  );
}

export const appModule: AppModule = {
  id: "workspace",
  routes: [
    ["/workspaces", (ctx) => <WorkspaceList ctx={ctx} />],
    ["/workspaces/:orgId", (ctx) => <Overview ctx={ctx} />],
    ["/workspaces/:orgId/profile", (ctx) => <Profile ctx={ctx} />],
    ["/workspaces/:orgId/members", (ctx) => <Members ctx={ctx} />],
    ["/workspaces/:orgId/returns", (ctx) => <ReturnsList ctx={ctx} />],
    ["/workspaces/:orgId/returns/:returnId", (ctx) => <ReturnPage ctx={ctx} />],
    ["/workspaces/:orgId/documents", (ctx) => <Documents ctx={ctx} />],
    ["/workspaces/:orgId/payments", (ctx) => <Payments ctx={ctx} />],
    ["/workspaces/:orgId/audit", (ctx) => <Audit ctx={ctx} />],
    ["/filing", (ctx) => <Filing ctx={ctx} />],
    ["/invite/:token", (ctx) => <AcceptInvitation ctx={ctx} />],
  ],
  dashboard: (ctx) => <DashboardCard key="workspace" ctx={ctx} />,
};
