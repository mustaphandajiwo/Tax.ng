// Display formatting only. Values arrive as decimal strings from the API.

const ngn = new Intl.NumberFormat("en-NG", { maximumFractionDigits: 2, minimumFractionDigits: 0 });

export function naira(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n)) return value;
  const sign = n < 0 ? "−" : "";
  return `${sign}₦${ngn.format(Math.abs(n))}`;
}

export function percent(rate: string): string {
  const n = Number(rate) * 100;
  return `${Number(n.toFixed(4))}%`;
}

export function date(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

export const REVIEW_LABEL: Record<string, string> = {
  unverified: "Unverified",
  secondary_source: "Secondary source",
  legal_approved: "Legally approved",
};

export const REGIME_LABEL: Record<string, string> = {
  nta2025: "Nigeria Tax Act 2025",
  pita: "Personal Income Tax Act (prior regime)",
  wht_regulations: "Withholding tax regulations",
  vat_act: "VAT (prior regime)",
};
