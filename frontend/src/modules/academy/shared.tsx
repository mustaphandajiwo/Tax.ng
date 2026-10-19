// Pieces shared by the public academy pages and the signed-in player.
import { ReviewBadge } from "../../components/ui";
import type { Cpd, Price, Trainer } from "./api";

export function CpdStatus({ cpd }: { cpd: Cpd | null }) {
  if (!cpd) return <span className="pill pill--muted">No CPD accreditation claimed</span>;
  return (
    <span className="pill pill--ok">
      CPD accredited by {cpd.body} · ref {cpd.reference}
    </span>
  );
}

export function PriceTag({ price }: { price: Price }) {
  if (price.model === "free") return <span className="pill pill--ok">Free</span>;
  return (
    <span className="pill pill--warn" title={price.note}>
      Price: {price.label.toLowerCase()}
    </span>
  );
}

export function TrainerCard({ trainer }: { trainer: Trainer }) {
  return (
    <div className="card academy-trainer">
      <p className="eyebrow">Trainer</p>
      <h3>{trainer.name}</h3>
      {trainer.sample && <span className="badge badge--unverified">Sample profile</span>}
      <p className="small">{trainer.headline}</p>
      {trainer.bio.map((p, i) => (
        <p key={i} className="small">
          {p}
        </p>
      ))}
    </div>
  );
}

export function CourseMeta({ review, level, hours }: { review: string; level: string; hours: number | null }) {
  return (
    <p className="academy-meta small">
      <ReviewBadge status={review} />
      {level && <span>{level}</span>}
      {hours ? <span>About {hours} hours</span> : null}
    </p>
  );
}

export const CALC_PATH: Record<string, string> = {
  pit: "/calculators/pit",
  "pit-compare": "/calculators/pit-compare",
  vat: "/calculators/vat",
  cit: "/calculators/cit",
  wht: "/calculators/wht",
};
