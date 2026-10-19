// Calculator pages (CALC-01 to CALC-05). Forms collect inputs; every number in
// the result comes from the calculation API.
import { useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, type CalcResult, type CompareResult, type Meta } from "../api";
import { ResultView } from "../components/ResultView";
import { CheckField, MoneyField, Notice, SelectField, errorText } from "../components/ui";
import { naira, percent } from "../format";
import { Link } from "../router";

const today = () => new Date().toISOString().slice(0, 10);

function useCalc<T>(run: (payload: Record<string, unknown>) => Promise<T>, id: string) {
  const [result, setResult] = useState<T>();
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const submit = async (payload: Record<string, unknown>) => {
    setBusy(true);
    setError(undefined);
    setFields({});
    void api.event("calculator_started", { calculator: id });
    try {
      const r = await run(payload);
      setResult(r);
      void api.event("calculator_completed", { calculator: id });
    } catch (err) {
      setResult(undefined);
      if (err instanceof ApiError && Object.keys(err.fields).length) setFields(err.fields);
      else setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return { result, fields, error, busy, submit };
}

function CalcShell(props: { title: string; intro: ReactNode; form: ReactNode; result: ReactNode; error?: string }) {
  return (
    <div className="calc">
      <p className="crumbs">
        <Link to="/calculators">Calculators</Link>
      </p>
      <h1>{props.title}</h1>
      <p className="lede">{props.intro}</p>
      <div className="calc__grid">
        <div className="card">{props.form}</div>
        <div>
          {props.error && <Notice tone="error">{props.error}</Notice>}
          {props.result ?? <p className="muted placeholder">Enter your figures to see the result and how it was worked out.</p>}
        </div>
      </div>
    </div>
  );
}

const YEARS = [
  { value: "2026", label: "2026 (Nigeria Tax Act 2025)" },
  { value: "2025", label: "2025 (Personal Income Tax Act)" },
];

// ------------------------------------------------------------------ PIT / PAYE
export function PitCalculator({ meta }: { meta: Meta }) {
  const [year, setYear] = useState("2026");
  const [gross, setGross] = useState("");
  const [rent, setRent] = useState("");
  const [deductions, setDeductions] = useState<Record<string, string>>({});
  const calc = useCalc((p) => api.calculate("pit", p), "pit");

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void calc.submit({ tax_year: Number(year), annual_gross_income: gross, annual_rent_paid: rent, ...deductions });
  };
  const r = calc.result;
  return (
    <CalcShell
      title="PAYE and personal income tax"
      intro="Work out annual personal income tax and monthly PAYE. Choose 2025 to see the old rules."
      error={calc.error}
      form={
        <form onSubmit={onSubmit} noValidate>
          <SelectField label="Tax year" value={year} options={YEARS} onChange={setYear} error={calc.fields.tax_year} />
          <MoneyField label="Gross annual income" required value={gross} onChange={setGross} error={calc.fields.annual_gross_income} hint="Salary, allowances and benefits for the year" />
          <MoneyField label="Annual rent paid on your home" value={rent} onChange={setRent} error={calc.fields.annual_rent_paid} hint="For rent relief (2026 onwards)" />
          <fieldset>
            <legend>Deductions for the year</legend>
            {meta.pit_deductions.map((d) => (
              <MoneyField
                key={d.id}
                label={d.label}
                value={deductions[d.id] ?? ""}
                error={calc.fields[d.id]}
                onChange={(v) => setDeductions({ ...deductions, [d.id]: v })}
              />
            ))}
          </fieldset>
          <button className="btn" disabled={calc.busy}>
            {calc.busy ? "Calculating…" : "Calculate"}
          </button>
          <p className="small">
            <Link to="/calculators/pit-compare">Compare the old and new law</Link>
          </p>
        </form>
      }
      result={
        r && (
          <ResultView
            result={r}
            headlines={[
              { label: "Annual tax", value: naira(r.outputs.annual_tax as string) },
              { label: "Monthly PAYE", value: naira(r.outputs.monthly_tax as string) },
              { label: "Effective rate", value: `${r.outputs.effective_rate_percent}%` },
            ]}
          />
        )
      }
    />
  );
}

// ------------------------------------------------------------- old vs new law
export function CompareCalculator() {
  const [gross, setGross] = useState("");
  const [pension, setPension] = useState("");
  const [rent, setRent] = useState("");
  const calc = useCalc((p) => api.compare(p), "pit-compare");
  const r: CompareResult | undefined = calc.result;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void calc.submit({ annual_gross_income: gross, pension, annual_rent_paid: rent });
  };
  const verdict = r
    ? r.difference.direction === "same"
      ? "No change"
      : `${naira(r.difference.annual_change.replace("-", ""))} a year ${r.difference.direction}`
    : "";
  return (
    <CalcShell
      title="Old law versus new law"
      intro="The same income under the 2025 rules and the 2026 rules, side by side."
      error={calc.error}
      form={
        <form onSubmit={onSubmit} noValidate>
          <MoneyField label="Gross annual income" required value={gross} onChange={setGross} error={calc.fields.annual_gross_income} />
          <MoneyField label="Annual pension contribution" value={pension} onChange={setPension} error={calc.fields.pension} />
          <MoneyField label="Annual rent paid on your home" value={rent} onChange={setRent} hint="Counts only under the new law" />
          <button className="btn" disabled={calc.busy}>
            {calc.busy ? "Comparing…" : "Compare"}
          </button>
        </form>
      }
      result={
        r && (
          <section className="result" aria-live="polite">
            <div className="result__head">
              <div className="stat">
                <span className="stat__label">2025 (old law)</span>
                <span className="stat__value">{naira(r.old.outputs.annual_tax as string)}</span>
              </div>
              <div className="stat">
                <span className="stat__label">2026 (new law)</span>
                <span className="stat__value">{naira(r.new.outputs.annual_tax as string)}</span>
              </div>
              <div className={`stat stat--${r.difference.direction}`}>
                <span className="stat__label">Change</span>
                <span className="stat__value">{verdict}</span>
              </div>
            </div>
            <p className="muted small">
              Monthly PAYE moves from {naira(r.old.outputs.monthly_tax as string)} to {naira(r.new.outputs.monthly_tax as string)}.
            </p>
            <details>
              <summary>2025 working (Personal Income Tax Act)</summary>
              <ResultView result={r.old} headlines={[{ label: "Annual tax", value: naira(r.old.outputs.annual_tax as string) }]} />
            </details>
            <details open>
              <summary>2026 working (Nigeria Tax Act 2025)</summary>
              <ResultView result={r.new} headlines={[{ label: "Annual tax", value: naira(r.new.outputs.annual_tax as string) }]} />
            </details>
          </section>
        )
      }
    />
  );
}

// -------------------------------------------------------------- CIT and levy
export function CitCalculator() {
  const [v, setV] = useState({ annual_turnover: "", fixed_assets: "", total_profits: "", assessable_profits: "" });
  const [flags, setFlags] = useState({ professional_services: false, non_resident: false });
  const calc = useCalc((p) => api.calculate("cit", p), "cit");
  const set = (k: keyof typeof v) => (x: string) => setV({ ...v, [k]: x });
  const r: CalcResult | undefined = calc.result;
  return (
    <CalcShell
      title="Company income tax and development levy"
      intro="Checks the small company test, then applies companies income tax and the development levy for 2026 onwards."
      error={calc.error}
      form={
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void calc.submit({ tax_year: 2026, ...v, ...flags });
          }}
        >
          <MoneyField label="Annual gross turnover" required value={v.annual_turnover} onChange={set("annual_turnover")} error={calc.fields.annual_turnover} />
          <MoneyField label="Total fixed assets" value={v.fixed_assets} onChange={set("fixed_assets")} error={calc.fields.fixed_assets} />
          <MoneyField label="Total profits (after capital allowances and losses)" required value={v.total_profits} onChange={set("total_profits")} error={calc.fields.total_profits} />
          <MoneyField label="Assessable profits (levy base)" value={v.assessable_profits} onChange={set("assessable_profits")} hint="Leave blank to use total profits" />
          <CheckField label="Provides professional services" checked={flags.professional_services} onChange={(x) => setFlags({ ...flags, professional_services: x })} />
          <CheckField label="Non-resident company" checked={flags.non_resident} onChange={(x) => setFlags({ ...flags, non_resident: x })} />
          <button className="btn" disabled={calc.busy}>
            {calc.busy ? "Calculating…" : "Calculate"}
          </button>
        </form>
      }
      result={
        r && (
          <ResultView
            result={r}
            headlines={[
              { label: "Small company", value: r.outputs.is_small_company ? "Yes" : "No" },
              { label: "CIT", value: naira(r.outputs.cit as string) },
              { label: "Development levy", value: naira(r.outputs.development_levy as string) },
              { label: "Total", value: naira(r.outputs.total_tax as string) },
            ]}
          />
        )
      }
    />
  );
}

// ------------------------------------------------------------------------ VAT
export function VatCalculator({ meta }: { meta: Meta }) {
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("standard");
  const [inclusive, setInclusive] = useState(false);
  const calc = useCalc((p) => api.calculate("vat", p), "vat");
  const r = calc.result;
  const labels: Record<string, string> = { standard: "Standard-rated", zero_rated: "Zero-rated", exempt: "Exempt" };
  return (
    <CalcShell
      title="VAT"
      intro="Add VAT to a net price, or take it out of a VAT-inclusive price."
      error={calc.error}
      form={
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void calc.submit({ amount, category, amount_includes_vat: inclusive, supply_date: today() });
          }}
        >
          <MoneyField label="Amount" required value={amount} onChange={setAmount} error={calc.fields.amount} />
          <SelectField
            label="Type of supply"
            value={category}
            onChange={setCategory}
            options={meta.vat_categories.map((c) => ({ value: c, label: labels[c] ?? c }))}
          />
          <CheckField label="The amount already includes VAT" checked={inclusive} onChange={setInclusive} />
          <button className="btn" disabled={calc.busy}>
            {calc.busy ? "Calculating…" : "Calculate"}
          </button>
        </form>
      }
      result={
        r && (
          <ResultView
            result={r}
            headlines={[
              { label: "Net", value: naira(r.outputs.net_amount as string) },
              { label: `VAT at ${percent(r.outputs.rate as string)}`, value: naira(r.outputs.vat as string) },
              { label: "Gross", value: naira(r.outputs.gross_amount as string) },
            ]}
          />
        )
      }
    />
  );
}

// ------------------------------------------------------------------------ WHT
export function WhtCalculator({ meta }: { meta: Meta }) {
  const types = meta.wht_payment_types;
  const [type, setType] = useState(types.find((t) => t.id === "professional_fees")?.id ?? types[0].id);
  const [recipient, setRecipient] = useState("corporate");
  const [amount, setAmount] = useState("");
  const [hasTin, setHasTin] = useState(true);
  const [payerSmall, setPayerSmall] = useState(false);
  const calc = useCalc((p) => api.calculate("wht", p), "wht");
  const allowed = types.find((t) => t.id === type)?.recipients ?? [];
  const r = calc.result;
  return (
    <CalcShell
      title="Withholding tax"
      intro="How much to deduct from a payment to a Nigerian resident, and what the recipient receives."
      error={calc.error}
      form={
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void calc.submit({
              payment_type: type,
              recipient_type: allowed.includes(recipient) ? recipient : allowed[0],
              amount,
              recipient_has_tin: hasTin,
              payer_is_small_company: payerSmall,
              payment_date: today(),
            });
          }}
        >
          <SelectField label="Payment type" value={type} onChange={setType} options={types.map((t) => ({ value: t.id, label: t.label }))} />
          <SelectField
            label="Recipient"
            value={allowed.includes(recipient) ? recipient : allowed[0]}
            onChange={setRecipient}
            error={calc.fields.recipient_type}
            options={allowed.map((x) => ({ value: x, label: x === "corporate" ? "A company" : "An individual or other non-corporate" }))}
          />
          <MoneyField label="Payment amount" required value={amount} onChange={setAmount} error={calc.fields.amount} />
          <CheckField label="Recipient has a valid TIN" checked={hasTin} onChange={setHasTin} />
          <CheckField label="We (the payer) are a small company" checked={payerSmall} onChange={setPayerSmall} />
          <button className="btn" disabled={calc.busy}>
            {calc.busy ? "Calculating…" : "Calculate"}
          </button>
        </form>
      }
      result={
        r && (
          <ResultView
            result={r}
            headlines={[
              { label: "Rate", value: percent(r.outputs.rate as string) },
              { label: "Deduct and remit", value: naira(r.outputs.wht as string) },
              { label: "Pay the recipient", value: naira(r.outputs.net_payment as string) },
            ]}
          />
        )
      }
    />
  );
}

// ---------------------------------------------------------------------- index
const CALCS = [
  { path: "/calculators/pit", title: "PAYE and personal income tax", text: "Annual tax and monthly PAYE, with rent relief and deductions." },
  { path: "/calculators/pit-compare", title: "Old law versus new law", text: "See how the 2026 rules change your tax." },
  { path: "/calculators/cit", title: "Company income tax", text: "Small company test, CIT and the development levy." },
  { path: "/calculators/vat", title: "VAT", text: "Add or extract VAT for standard, zero-rated and exempt supplies." },
  { path: "/calculators/wht", title: "Withholding tax", text: "Deduction at source by payment type and recipient." },
];

export function CalculatorIndex() {
  return (
    <>
      <h1>Calculators</h1>
      <p className="lede">Every calculator shows its working, the provisions it relies on and the rules version used.</p>
      <div className="cards">
        {CALCS.map((c) => (
          <Link key={c.path} to={c.path} className="card card--link">
            <h2>{c.title}</h2>
            <p>{c.text}</p>
          </Link>
        ))}
      </div>
    </>
  );
}
