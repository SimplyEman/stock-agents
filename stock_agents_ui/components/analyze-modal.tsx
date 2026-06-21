"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  analyzeTheme,
  estimateCostUsd,
  fetcher,
  HUNT_PROFILES,
  type AnalyzeOptions,
  type HuntProfile,
  type Theme,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  onClose: () => void;
  initialTheme?: string;
}

function toStr(v: number | undefined | null) {
  return v == null ? "" : String(v);
}

export function AnalyzeModal({ onClose, initialTheme = "" }: Props) {
  const themes = useSWR<Theme[]>("/api/themes", fetcher);
  // Default to "Picks-and-shovels" — sensible middle ground.
  const [profile, setProfile] = useState<HuntProfile>(HUNT_PROFILES[1]);
  const [theme, setTheme] = useState(initialTheme);
  const [busy, setBusy] = useState(false);

  // Form state mirrors the selected profile; user can override any field.
  const [maxCandidates, setMaxCandidates] = useState(profile.options.max_candidates ?? 5);
  const [forensic, setForensic] = useState(!!profile.options.forensic);
  const [currency, setCurrency] = useState<"gbp" | "usd">(profile.options.currency ?? "gbp");
  const [minCap, setMinCap] = useState(toStr(profile.options.min_market_cap_gbp));
  const [maxCap, setMaxCap] = useState(toStr(profile.options.max_market_cap_gbp));
  const [maxPrice, setMaxPrice] = useState(toStr(profile.options.max_price_gbp));
  const [max12m, setMax12m] = useState(toStr(profile.options.max_12m_return_pct));

  function applyProfile(p: HuntProfile) {
    setProfile(p);
    setMaxCandidates(p.options.max_candidates ?? 5);
    setForensic(!!p.options.forensic);
    setCurrency(p.options.currency ?? "gbp");
    setMinCap(toStr(p.options.min_market_cap_gbp));
    setMaxCap(toStr(p.options.max_market_cap_gbp));
    setMaxPrice(toStr(p.options.max_price_gbp));
    setMax12m(toStr(p.options.max_12m_return_pct));
  }

  function numOrUndef(s: string) {
    const n = Number(s);
    return s.trim() === "" || Number.isNaN(n) ? undefined : n;
  }

  const opts: AnalyzeOptions = useMemo(() => ({
    max_candidates: maxCandidates,
    forensic,
    currency,
    min_market_cap_gbp: numOrUndef(minCap),
    max_market_cap_gbp: numOrUndef(maxCap),
    max_price_gbp: numOrUndef(maxPrice),
    max_12m_return_pct: numOrUndef(max12m),
  }), [maxCandidates, forensic, currency, minCap, maxCap, maxPrice, max12m]);

  const [costLo, costHi] = estimateCostUsd(opts);

  async function go() {
    if (!theme) return;
    setBusy(true);
    try {
      await analyzeTheme(theme, opts);
      onClose();
    } finally {
      setBusy(false);
    }
  }

  const input = "rounded-md border border-input bg-background px-3 py-2 text-sm w-full";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <Card className="w-full max-w-2xl max-h-[92vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <CardHeader>
          <CardTitle>Configure run</CardTitle>
          <p className="text-xs text-muted-foreground">
            Pick what kind of stock you&apos;re looking for, then tweak any filter before launching.
          </p>
        </CardHeader>
        <CardContent className="flex flex-col gap-5 text-sm">

          {/* Hunt profile picker */}
          <div className="flex flex-col gap-2">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              What are you hunting for?
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              {HUNT_PROFILES.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => applyProfile(p)}
                  className={cn(
                    "rounded-md border px-3 py-2 text-left text-xs transition-colors",
                    profile.id === p.id
                      ? "border-accent bg-accent/10 text-foreground"
                      : "border-border text-muted-foreground hover:bg-muted/50",
                  )}
                >
                  <div className="font-medium text-foreground">{p.label}</div>
                  <div className="mt-0.5 leading-snug">{p.blurb}</div>
                </button>
              ))}
            </div>
            {profile.notes && (
              <p className="text-xs text-muted-foreground">{profile.notes}</p>
            )}
          </div>

          {/* Theme */}
          {initialTheme ? (
            <div className="rounded-md border border-border bg-muted/30 px-3 py-2 font-mono text-sm">
              {initialTheme}
            </div>
          ) : (
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Theme
              </span>
              <input
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                list="theme-options"
                placeholder='e.g. "AI semiconductor test equipment"'
                className={input}
              />
              <datalist id="theme-options">
                {themes.data?.map((t) => <option key={t.theme} value={t.theme} />)}
              </datalist>
              <span className="text-xs text-muted-foreground">
                Pick from the suggested themes or type a free-form one — narrower themes give
                more interesting picks.
              </span>
            </label>
          )}

          {/* Filters */}
          <div className="flex flex-col gap-3 rounded-md border border-border p-3">
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Filters
              </div>
              <button
                type="button"
                onClick={() => applyProfile(profile)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Reset to profile defaults
              </button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Max candidates" type="number" value={String(maxCandidates)}
                setValue={(v) => setMaxCandidates(Number(v) || 5)} />
              <label className="flex items-end gap-2 pb-2">
                <input type="checkbox" checked={forensic} onChange={(e) => setForensic(e.target.checked)} />
                <span className="text-xs">Forensic agent</span>
              </label>
            </div>

            <div className="flex items-center gap-3">
              <span className="text-xs uppercase text-muted-foreground">Currency</span>
              <label className="flex items-center gap-1 text-xs">
                <input type="radio" name="cur" checked={currency === "gbp"} onChange={() => setCurrency("gbp")} /> GBP
              </label>
              <label className="flex items-center gap-1 text-xs">
                <input type="radio" name="cur" checked={currency === "usd"} onChange={() => setCurrency("usd")} /> USD
              </label>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Min market cap" value={minCap} setValue={setMinCap}
                placeholder="e.g. 500000000" hint={prettyCap(minCap)} />
              <Field label="Max market cap" value={maxCap} setValue={setMaxCap}
                placeholder="e.g. 3000000000" hint={prettyCap(maxCap)} />
              <Field label="Max share price" value={maxPrice} setValue={setMaxPrice}
                placeholder="rarely used" />
              <Field label="Max 12-month return %" value={max12m} setValue={setMax12m}
                placeholder="e.g. 50 → drops 1.5×'ers"
                hint={max12m !== "" && Number(max12m) <= 0
                  ? "Negative-momentum mode: only flat/down names"
                  : undefined} />
            </div>
          </div>

          {/* Cost + actions */}
          <div className="text-xs text-muted-foreground">
            Estimated cost:{" "}
            <span className="font-mono text-foreground">${costLo.toFixed(1)}–${costHi.toFixed(1)}</span>{" "}
            equivalent (Max usage, not billed)
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button onClick={go} disabled={!theme || busy}>
              {busy ? "Starting…" : "Run analysis"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function prettyCap(s: string): string {
  const n = Number(s);
  if (!Number.isFinite(n) || n <= 0) return "";
  if (n >= 1e9) return `≈ ${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `≈ ${(n / 1e6).toFixed(0)}M`;
  return s;
}

function Field({
  label, value, setValue, placeholder, type = "text", hint,
}: {
  label: string;
  value: string;
  setValue: (v: string) => void;
  placeholder?: string;
  type?: "text" | "number";
  hint?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        className="rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
      />
      {hint && <span className="text-[10px] text-muted-foreground">{hint}</span>}
    </label>
  );
}
