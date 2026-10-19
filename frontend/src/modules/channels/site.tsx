// Public channel pages: the WhatsApp demo and language availability.
import { useState } from "react";
import { Loading, Notice, useLoad } from "../../components/ui";
import type { SiteModule } from "../types";
import { channelsApi } from "./api";
import { WhatsAppSimulator } from "./shared";

function WhatsAppPage() {
  return (
    <article className="article">
      <h1>tax.ng on WhatsApp</h1>
      <p className="lede">
        Ask a tax question or work out PAYE and VAT from a chat. Figures come from the same rules engine as the calculators, and answers cite
        the law.
      </p>
      <Notice tone="warn">
        Demo only. The WhatsApp number is not live yet: it needs a WhatsApp Business API provider, a verified business number and approved
        message templates. Use the simulator to see how the bot replies.
      </Notice>
      <div className="grid-2">
        <WhatsAppSimulator />
        <div className="card">
          <h2>What you can send</h2>
          <ul className="list list--tight">
            <li>
              <strong>PAYE 6m</strong>
              <span>Annual tax and monthly PAYE on a yearly salary.</span>
            </li>
            <li>
              <strong>tax 450k monthly</strong>
              <span>A monthly salary, converted to annual before the calculation.</span>
            </li>
            <li>
              <strong>VAT 100000</strong>
              <span>VAT at the standard rate. Add "inclusive" to extract VAT from a total.</span>
            </li>
            <li>
              <strong>Any question</strong>
              <span>Answered by Tax AI from the legal library, with sources.</span>
            </li>
            <li>
              <strong>STOP</strong>
              <span>No more alerts. You can still ask questions. START turns alerts back on.</span>
            </li>
          </ul>
          <p className="small">General information, not tax advice.</p>
        </div>
      </div>
    </article>
  );
}

function LanguagesPage() {
  const { data, error } = useLoad(() => channelsApi.languages(), []);
  const [lang, setLang] = useState("");
  const cat = useLoad(() => (lang ? channelsApi.catalogue(lang) : Promise.resolve(null)), [lang]);
  return (
    <article className="article">
      <h1>Languages</h1>
      <p className="lede">
        tax.ng is written in English. We are preparing Hausa, Yoruba, Igbo and Nigerian Pidgin, and we publish a translation only after a
        reviewer has checked it.
      </p>
      <h2>How a translation goes live</h2>
      <ol>
        <li>A member of staff drafts or submits a translation of a page element or a guide summary.</li>
        <li>A different reviewer, from our legal or editorial team, checks the meaning and the tax terms.</li>
        <li>Only approved text is shown. Anything not yet approved stays in English.</li>
      </ol>
      <p>If a translation and the English version ever differ, the English version applies.</p>
      {!data ? (
        <Loading error={error} />
      ) : (
        <div className="grid-2">
          <section className="card">
            <h2>Available now</h2>
            <ul className="list list--tight">
              {data.languages.map((l) => (
                <li key={l.lang}>
                  <strong lang={l.lang}>{l.native_name}</strong>
                  <span>
                    {l.status === "source" ? "Source language" : `${l.approved} of ${l.total} interface strings reviewed`}{" "}
                    {l.status === "reviewed" && (
                      <button type="button" className="btn btn--small btn--ghost" onClick={() => setLang(l.lang)}>
                        Preview
                      </button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          <section className="card">
            <h2>In preparation</h2>
            <ul className="list list--tight">
              {data.in_review.map((l) => (
                <li key={l.lang}>
                  <strong lang={l.lang}>
                    {l.native_name} ({l.name})
                  </strong>
                  <span>{l.approved > 0 ? `${l.approved} strings reviewed` : "Not yet reviewed"}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
      {lang && (
        <section aria-live="polite">
          <h2>Preview</h2>
          {!cat.data ? (
            <Loading error={cat.error} />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Element</th>
                    <th scope="col">Text</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(cat.data.strings).map(([k, v]) => (
                    <tr key={k}>
                      <th scope="row">
                        <code>{k}</code>
                      </th>
                      <td lang={cat.data!.fallback_keys.includes(k) ? "en" : lang}>
                        {v} {cat.data!.fallback_keys.includes(k) && <span className="pill pill--muted">English</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </article>
  );
}

export const siteModule: SiteModule = {
  id: "channels",
  routes: [
    ["/whatsapp", () => <WhatsAppPage />],
    ["/languages", () => <LanguagesPage />],
  ],
};
