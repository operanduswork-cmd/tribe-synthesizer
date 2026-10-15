// Small number and date formats shared by the screens. Display only; no copy text here.

/** Dollars for an estimate: three decimals under a cent ($0.003), else two ($0.10). */
export function formatUsd(usd: number): string {
  return usd < 0.01 && usd > 0 ? usd.toFixed(3) : usd.toFixed(2);
}

/** "2026-10-09 10:15" in UTC from an ISO string (stable on server and client). */
export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toISOString().slice(0, 16).replace("T", " ");
}
