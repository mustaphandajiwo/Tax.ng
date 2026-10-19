// Renders parameter values exactly as the rules engine returns them.
// Pages never type a rate or threshold themselves (CALC-07).
import type { ParameterCard } from "../api";
import { naira, percent } from "../format";
import { ReviewBadge } from "./ui";

function display(card: ParameterCard): string {
  const v = card.value;
  if (Array.isArray(v)) return v.join("; ");
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (v === undefined) return "";
  if (card.unit === "currency-NGN") return naira(v);
  if (card.unit === "/1") return percent(v);
  return v;
}

export function Figure({ card }: { card: ParameterCard }) {
  if (!card.in_force) {
    return (
      <div className="figure figure--off">
        <span className="figure__label">{card.description}</span>
        <span className="figure__value">Not in force on this date</span>
      </div>
    );
  }
  return (
    <div className="figure">
      <span className="figure__label">{card.description}</span>
      {card.scale ? (
        <table className="table table--compact">
          <thead>
            <tr>
              <th scope="col">Band</th>
              <th scope="col">Rate</th>
            </tr>
          </thead>
          <tbody>
            {card.scale.map((b, i) => {
              const next = card.scale![i + 1];
              return (
                <tr key={b.threshold}>
                  <td>{next ? `${naira(b.threshold)} to ${naira(next.threshold)}` : `Above ${naira(b.threshold)}`}</td>
                  <td>{percent(b.rate)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <span className="figure__value">{display(card)}</span>
      )}
      <span className="figure__meta">
        <ReviewBadge status={card.review_status} />
        {card.reference && (
          <a href={card.reference} target="_blank" rel="noreferrer">
            Source
          </a>
        )}
      </span>
    </div>
  );
}

export function Figures({ cards }: { cards: ParameterCard[] }) {
  if (!cards.length) return null;
  return (
    <div className="figures" aria-label="Current figures from the rules engine">
      <p className="eyebrow">From the rules engine</p>
      {cards.map((c) => (
        <Figure key={c.name} card={c} />
      ))}
    </div>
  );
}
