// CALC-06 calculator pages: capital gains and stamp duty. Inputs only; every
// figure in the result comes from the calculation API and the rules engine.
import { useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, type CalcResult } from "../../api";
import { ResultView } from "../../components/ResultView";
import { CheckField, MoneyField, Notice, SelectField, errorText } from "../../components/ui";
import { naira, percent } from "../../format";
import { Link } from "../../router";

const today = () => new Date().toISOString().slice(0, 10);

function useCalc(id: string) {
  const [result, setResult] = useState<CalcResult>();
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const submit = async (payload: Record<string, unknown>) => {
    setBusy(true);
    setError(undefined);
    setFields({});
    void api.event("calculator_started", { calculator: id });
    try {
      setResult(await api.calculate(id, payload));
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

function Shell(props: { title: string; intro: ReactNode; form: ReactNode; result: ReactNode; error?: string }) {
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

const ASSETS = [
  { value: "shares", label: "Shares" },
  { value: "land_buildings", label: "Land or buildings" },
  { value: "chattel", label: "Personal belongings (chattels)" },
  { value: "other", label: "Other asset" },
];

export function CgtCalculator() {
  const [taxpayer, setTaxpayer] = useState("individual");
  const [asset, setAsset] = useState("shares");
  const [disposalDate, setDisposalDate] = useState(today());
  const [v, setV] = useState<Record<string, string>>({});
  const [professional, setProfessional] = useState(false);
  const calc = useCalc("cgt");
  const set = (k: string) => (x: string) => setV({ ...v, [k]: x });
  const r = calc.result;
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void calc.submit({ taxpayer_type: taxpayer, asset_type: asset, disposal_date: disposalDate, ...v, professional_services: professional });
  };
  return (
    <Shell
      title="Capital gains"
      intro="Work out the gain on selling an asset and the tax on it under the Nigeria Tax Act 2025, including the share and personal belongings exemptions."
      error={calc.error}
      form={
        <form onSubmit={onSubmit} noValidate>
          <SelectField
            label="Who is selling?"
            value={taxpayer}
            onChange={setTaxpayer}
            options={[
              { value: "individual", label: "An individual" },
              { value: "company", label: "A company" },
            ]}
            error={calc.fields.taxpayer_type}
          />
          <SelectField label="What was sold?" value={asset} onChange={setAsset} options={ASSETS} error={calc.fields.asset_type} />
          <div className={`field${calc.fields.disposal_date ? " field--error" : ""}`}>
            <label htmlFor="cgt-date">Date of disposal</label>
            <input id="cgt-date" type="date" value={disposalDate} onChange={(e) => setDisposalDate(e.target.value)} />
            {calc.fields.disposal_date && <p className="field__hint">{calc.fields.disposal_date}</p>}
          </div>
          <MoneyField label="Disposal proceeds" required value={v.proceeds ?? ""} onChange={set("proceeds")} error={calc.fields.proceeds} />
          <MoneyField label="Cost of acquisition" value={v.cost ?? ""} onChange={set("cost")} error={calc.fields.cost} />
          <MoneyField label="Allowable expenses of buying and selling" value={v.allowable_expenses ?? ""} onChange={set("allowable_expenses")} error={calc.fields.allowable_expenses} />
          {asset === "shares" && (
            <fieldset>
              <legend>Other share disposals in the same twelve months</legend>
              <MoneyField label="Their total proceeds" value={v.prior_share_proceeds_12m ?? ""} onChange={set("prior_share_proceeds_12m")} />
              <MoneyField label="Their total gains" value={v.prior_share_gains_12m ?? ""} onChange={set("prior_share_gains_12m")} />
            </fieldset>
          )}
          {taxpayer === "company" ? (
            <>
              <MoneyField label="Company's annual turnover" required value={v.annual_turnover ?? ""} onChange={set("annual_turnover")} error={calc.fields.annual_turnover} />
              <MoneyField label="Company's total fixed assets" value={v.fixed_assets ?? ""} onChange={set("fixed_assets")} error={calc.fields.fixed_assets} />
              <CheckField label="The company provides professional services" checked={professional} onChange={setProfessional} />
            </>
          ) : (
            <MoneyField
              label="Your other chargeable income for the year"
              value={v.other_chargeable_income ?? ""}
              onChange={set("other_chargeable_income")}
              hint="The gain is added to this income"
              error={calc.fields.other_chargeable_income}
            />
          )}
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
              { label: "Chargeable gain", value: naira(r.outputs.chargeable_gain as string) },
              { label: "Exempt", value: r.outputs.exempt ? "Yes" : "No" },
              ...(typeof r.outputs.rate === "string" ? [{ label: "Rate", value: percent(r.outputs.rate) }] : []),
              { label: "Tax on the gain", value: naira(r.outputs.cgt as string) },
            ]}
          />
        )
      }
    />
  );
}

export function StampDutyCalculator() {
  const [instrument, setInstrument] = useState("electronic_transfer");
  const [amount, setAmount] = useState("");
  const [own, setOwn] = useState(false);
  const calc = useCalc("stamp-duty");
  const r = calc.result;
  return (
    <Shell
      title="Stamp duty"
      intro="The electronic money transfer levy, and duty on a company's share capital."
      error={calc.error}
      form={
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void calc.submit({ instrument, amount, own_account: instrument === "electronic_transfer" && own, transaction_date: today() });
          }}
        >
          <SelectField
            label="What is being stamped?"
            value={instrument}
            onChange={setInstrument}
            options={[
              { value: "electronic_transfer", label: "An electronic receipt or transfer" },
              { value: "share_capital", label: "Share capital (incorporation or new shares)" },
            ]}
            error={calc.fields.instrument}
          />
          <MoneyField
            label={instrument === "share_capital" ? "Authorised share capital (or the increase)" : "Amount received or transferred"}
            required
            value={amount}
            onChange={setAmount}
            error={calc.fields.amount}
          />
          {instrument === "electronic_transfer" && (
            <CheckField label="Between my own accounts in the same bank" checked={own} onChange={setOwn} />
          )}
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
              { label: "Duty", value: naira(r.outputs.duty as string) },
              ...(typeof r.outputs.rate === "string" ? [{ label: "Rate", value: percent(r.outputs.rate) }] : []),
              { label: "Exempt or below threshold", value: r.outputs.exempt ? "Yes" : "No" },
            ]}
          />
        )
      }
    />
  );
}
