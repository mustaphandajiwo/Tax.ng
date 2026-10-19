// Public developer page (/developers): API overview, scopes, errors, webhooks, ERP connectors, sandbox note.
import { Loading, Notice, useLoad } from "../../components/ui";
import type { SiteModule } from "../types";
import { developerApi as api } from "./api";

const CURL = `curl -X POST https://tax.ng/api/v1/calculate/vat \\
  -H "Authorization: Bearer tng_test_..." \\
  -H "Content-Type: application/json" \\
  -H "X-Correlation-Id: my-trace-123" \\
  -d '{"amount": "100000", "category": "standard"}'`;

const VERIFY = `// Node.js: verify X-TaxNG-Signature on a webhook you receive
const [t, v1] = header.split(",").map((p) => p.split("=")[1]);
const expected = crypto.createHmac("sha256", secret).update(\`\${t}.\${rawBody}\`).digest("hex");
const fresh = Math.abs(Date.now() / 1000 - Number(t)) < 300;
const ok = fresh && crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(v1));`;

function Developers() {
  const cat = useLoad(() => api.catalogue(), []);
  const doc = useLoad(() => api.openapi(), []);
  const sandbox = cat.data ? Object.values(cat.data.modes).every((m) => m === "sandbox") : true;
  return (
    <article className="article">
      <p className="eyebrow">Developers and API</p>
      <h1>Build on tax.ng</h1>
      <p className="lede">
        A versioned API for the tax.ng calculators, effective-dated rules and NRS e-invoicing, with webhooks and ERP import connectors.
      </p>
      {sandbox && (
        <Notice tone="warn">
          The API runs in sandbox mode. E-invoices get sandbox references and are not sent to NRS. Webhooks are recorded, not sent. Live
          e-invoicing needs NRS accreditation as a system integrator or access point provider.
        </Notice>
      )}
      <p>
        <a className="btn" href="/api/v1/openapi.json">
          OpenAPI 3.1 document (JSON)
        </a>{" "}
        <a className="btn btn--ghost" href="/app/#/integrations">
          Get an API key
        </a>
      </p>

      <h2>Quick start</h2>
      <p>Create a key in Integrations (workspace owners only). It is shown once; tax.ng stores only a hash.</p>
      <pre className="dev-code">{CURL}</pre>

      <h2>Endpoints</h2>
      {!doc.data ? (
        <Loading error={doc.error} />
      ) : (
        <div className="table-wrap">
          <table className="table table--compact">
            <thead>
              <tr>
                <th scope="col">Method and path</th>
                <th scope="col">What it does</th>
                <th scope="col">Scope</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(doc.data.paths).flatMap(([path, methods]) =>
                Object.entries(methods).map(([method, op]) => (
                  <tr key={`${method} ${path}`}>
                    <th scope="row">
                      <code>
                        {method.toUpperCase()} {path}
                      </code>
                    </th>
                    <td>{op.summary}</td>
                    <td>{op["x-required-scope"] ?? (op.security && op.security.length === 0 ? "Public" : "Any key")}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      )}

      <h2>Conventions</h2>
      <ul>
        <li>
          <strong>Authentication:</strong> <code>Authorization: Bearer &lt;key&gt;</code>. Revoked keys stop working at once.
        </li>
        <li>
          <strong>Money:</strong> decimal strings such as <code>"1500.00"</code>, never floating-point numbers.
        </li>
        <li>
          <strong>Idempotency:</strong> send <code>Idempotency-Key</code> on POST. The same key and body return the stored response; a
          different body with the same key is refused.
        </li>
        <li>
          <strong>Tracing:</strong> <code>X-Correlation-Id</code> is echoed on every response, or generated for you.
        </li>
        <li>
          <strong>Rate limits:</strong> per key, as a token bucket. Responses carry <code>X-RateLimit-Limit</code> and{" "}
          <code>X-RateLimit-Remaining</code>; a 429 carries <code>Retry-After</code>.
        </li>
      </ul>

      <h2>Scopes</h2>
      {cat.data ? (
        <ul className="list list--tight">
          {cat.data.scopes.map((s) => (
            <li key={s.id}>
              <strong>
                <code>{s.id}</code>
              </strong>
              <span>{s.description}</span>
            </li>
          ))}
        </ul>
      ) : (
        <Loading error={cat.error} />
      )}

      <h2>Errors</h2>
      <p>
        Every error has the same shape: <code>{'{"error": code, "message", "fields"?, "correlation_id"}'}</code>.
      </p>
      {doc.data && (
        <ul className="list list--tight">
          {Object.entries(doc.data["x-error-codes"]).map(([code, text]) => (
            <li key={code}>
              <strong>
                <code>{code}</code>
              </strong>
              <span>{text}</span>
            </li>
          ))}
        </ul>
      )}

      <h2>Webhooks</h2>
      <p>
        Register an HTTPS endpoint and choose events. Each delivery is signed with your endpoint secret in <code>X-TaxNG-Signature</code>{" "}
        (<code>t=&lt;unix time&gt;,v1=&lt;HMAC-SHA256 of "t.body"&gt;</code>). Deduplicate on <code>X-TaxNG-Delivery</code>.
        {cat.data && ` Failed deliveries are retried after ${cat.data.retry_schedule_seconds.slice(1).map((s) => (s < 3600 ? `${s / 60} min` : `${s / 3600} h`)).join(", ")}.`}
      </p>
      <pre className="dev-code">{VERIFY}</pre>
      {cat.data && (
        <ul className="list list--tight">
          {cat.data.events.map((e) => (
            <li key={e.id}>
              <strong>
                <code>{e.id}</code>
              </strong>
              <span>{e.description}</span>
            </li>
          ))}
        </ul>
      )}

      <h2>ERP connectors</h2>
      <p>
        Import sales invoices from an ERP export (CSV or JSON). Mapping profiles below are starting points: confirm the columns against your
        own export. Live sync from each ERP needs licensed API access and is not yet available.
      </p>
      {cat.data && (
        <ul className="list list--tight">
          {cat.data.erp_profiles.map((p) => (
            <li key={p.id}>
              <strong>{p.label}</strong>
              <span>
                File import ({p.status}) · mapping {p.mapping_status}
                {p.live_sync ? ` · Live sync: ${p.live_sync}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

export const siteModule: SiteModule = {
  id: "developer",
  routes: [["/developers", () => <Developers />]],
};
