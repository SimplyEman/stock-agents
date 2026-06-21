// Thin client for the FastAPI backend. All calls are local-only.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8001";

export async function fetcher<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body == null ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export async function del<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// --- types mirroring the backend schemas ---------------------------------

export interface WatchlistEntry {
  ticker: string;
  status: string;
  entry_conviction: number;
  current_conviction: number | null;
  delta: number | null;
  entry_price: number | null;
  notes: string | null;
  added_at: string;
}

export interface Snapshot {
  id: string;
  taken_at: string;
  conviction: number;
  fundamentals_score: number | null;
  balance_sheet_score: number | null;
  management_score: number | null;
  stress_test_score: number | null;
  run_id: string;
}

export interface Run {
  id: string;
  kind: string;
  theme: string | null;
  ticker: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
  cost_estimate_usd: number | null;
  report_path: string | null;
  error: string | null;
}

export interface Alert {
  id: string;
  kind: string;
  ticker: string | null;
  severity: string;
  message: string;
  created_at: string;
  delivered_at: string | null;
  acknowledged_at: string | null;
}

export interface Theme {
  theme: string;
  etfs: string[];
  last_analyzed: string | null;
  top5: string[];
}

export interface Thesis {
  ticker: string;
  name: string;
  one_paragraph_summary: string;
  bull_case: string[];
  bear_case: string[];
  what_would_change_my_mind: string;
  catalysts: string[];
  conviction_score: number;
  conviction_label: string;
  fundamentals_score: number;
  balance_sheet_score: number;
  management_score: number;
  stress_test_score: number;
  peer_preference_strength: number | null;
  macro_fit: string;
  forensic_risk_score: number | null;
  sources: string[];
}

export interface AnalyzeOptions {
  max_candidates?: number;
  forensic?: boolean;
  min_market_cap_gbp?: number;
  max_market_cap_gbp?: number;
  max_price_gbp?: number;
  max_12m_return_pct?: number;
  currency?: "gbp" | "usd";
}

export function analyzeTheme(theme: string, opts: AnalyzeOptions = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(opts)) {
    if (v === undefined || v === null || v === "") continue;
    qs.set(k, String(v));
  }
  return post<{ run_id: string; status: string }>(
    `/api/themes/${encodeURIComponent(theme)}/analyze?${qs.toString()}`,
  );
}

// Named "hunt profiles" that translate stock-type intent into filter combinations.
// Selecting a profile pre-fills the modal; users can still override any field.
export interface HuntProfile {
  id: string;
  label: string;
  blurb: string;
  notes: string;
  options: AnalyzeOptions;
}

export const HUNT_PROFILES: HuntProfile[] = [
  {
    id: "tenx_hunt",
    label: "10x asymmetric hunt",
    blurb: "True small caps in a tailwind theme where the move hasn't happened yet",
    notes: "Strictest filters. Often returns 0–2 picks — that's correct. Forensic on.",
    options: {
      max_candidates: 5,
      forensic: true,
      currency: "gbp",
      min_market_cap_gbp: 200_000_000,
      max_market_cap_gbp: 1_000_000_000,
      max_12m_return_pct: 50,
    },
  },
  {
    id: "picks_and_shovels",
    label: "Picks-and-shovels mid-cap",
    blurb: "Quality mid-caps adjacent to a structural tailwind, not the obvious winners",
    notes: "Realistic 2–3x candidates. Drops names that 2x'd already.",
    options: {
      max_candidates: 5,
      forensic: true,
      currency: "gbp",
      min_market_cap_gbp: 500_000_000,
      max_market_cap_gbp: 3_000_000_000,
      max_12m_return_pct: 100,
    },
  },
  {
    id: "compounder",
    label: "Established compounder",
    blurb: "Larger names with quality fundamentals; size over upside math",
    notes: "Forensic optional. Less room for 10x; better odds the picks are real.",
    options: {
      max_candidates: 5,
      forensic: false,
      currency: "gbp",
      min_market_cap_gbp: 3_000_000_000,
      max_market_cap_gbp: 20_000_000_000,
    },
  },
  {
    id: "value_recovery",
    label: "Value / recovery",
    blurb: "Names that have gone nowhere or fallen — looking for inflection setups",
    notes: "Negative-momentum cap (max_12m_return ≤ 0). Pair with forensic to weed out value traps.",
    options: {
      max_candidates: 5,
      forensic: true,
      currency: "gbp",
      min_market_cap_gbp: 500_000_000,
      max_market_cap_gbp: 10_000_000_000,
      max_12m_return_pct: 0,
    },
  },
  {
    id: "baseline",
    label: "No filters (baseline)",
    blurb: "Original behaviour — mega-caps included, no momentum gate",
    notes: "Useful as a sanity check or when you want the unconstrained universe.",
    options: { max_candidates: 5, forensic: false, currency: "gbp" },
  },
  {
    id: "custom",
    label: "Custom",
    blurb: "Start blank and configure every field yourself",
    notes: "",
    options: { max_candidates: 5, forensic: false, currency: "gbp" },
  },
];

export function estimateCostUsd(opts: AnalyzeOptions): [number, number] {
  // Rough usage-equivalent estimate on the Max backend, not metered $.
  const n = opts.max_candidates ?? 5;
  const perCandidateLow = opts.forensic ? 2.0 : 1.0;
  const perCandidateHigh = opts.forensic ? 3.5 : 2.0;
  const overhead = 1.0; // macro + screener + validation + commentary
  return [n * perCandidateLow + overhead, n * perCandidateHigh + overhead];
}

export interface ThesisSnapshot {
  id: string;
  ticker: string;
  taken_at: string;
  thesis: Thesis;
}

export interface Settings {
  keys_configured: Record<string, boolean>;
  batch_themes: string[];
  alert_channel: string;
  weekly_budget_usd: number;
  daily_post_earnings_budget_usd: number;
  sunday_batch_budget_usd: number;
  llm_backend: string;
}
