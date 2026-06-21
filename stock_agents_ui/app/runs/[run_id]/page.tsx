"use client";

import { useParams } from "next/navigation";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ThesisCard } from "@/components/thesis-card";
import { API_BASE, fetcher, type Run, type Thesis } from "@/lib/api";

interface FinalReport {
  theme: string;
  run_timestamp: string;
  candidates_analyzed: number;
  api_cost_usd: number;
  market_commentary: string;
  filter_note?: string;
  top_picks: Thesis[];
  full_results: Thesis[];
}

export default function RunDetail() {
  const runId = String(useParams().run_id);
  const run = useSWR<Run>(`/api/runs/${runId}`, fetcher, { refreshInterval: 4000 });
  const hasReport = run.data?.status === "success" && run.data?.report_path;
  const report = useSWR<FinalReport | Record<string, unknown>>(
    hasReport ? `/api/runs/${runId}/report` : null, fetcher);

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold tracking-tight">Run detail</h1>

      {!run.data ? <Skeleton className="h-24 w-full" /> : (
        <Card>
          <CardContent className="grid grid-cols-2 gap-3 p-5 text-sm md:grid-cols-4">
            <Field label="Kind" value={run.data.kind} />
            <Field label="Target" value={run.data.ticker || run.data.theme || "—"} />
            <Field label="Status" value={run.data.status} />
            <Field label="Cost" value={run.data.cost_estimate_usd != null ? `$${run.data.cost_estimate_usd.toFixed(2)}` : "—"} />
            {run.data.error && <div className="col-span-full text-rose-400">Error: {run.data.error}</div>}
          </CardContent>
        </Card>
      )}

      {hasReport && (run.data!.report_path!.endsWith(".json")) && (
        <a href={`${API_BASE}/api/runs/${runId}/report`} target="_blank" rel="noreferrer"
          className="text-sm text-primary underline">Download report JSON</a>
      )}

      {report.data && "top_picks" in report.data && (
        <ReportView report={report.data as FinalReport} />
      )}
      {report.data && "thesis" in report.data && (
        <ThesisCard thesis={(report.data as { thesis: Thesis }).thesis} />
      )}
    </div>
  );
}

function ReportView({ report }: { report: FinalReport }) {
  const picks = report.top_picks?.length ? report.top_picks : report.full_results || [];
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader><CardTitle>{report.theme}</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-2 text-sm">
          <div className="flex gap-6 text-muted-foreground">
            <span>Analyzed: {report.candidates_analyzed}</span>
            <span>Cost: ${report.api_cost_usd?.toFixed(2)}</span>
          </div>
          {report.filter_note && (
            <p className="rounded-md border border-border/60 bg-muted/40 p-2 text-xs font-mono text-muted-foreground">
              {report.filter_note}
            </p>
          )}
          {report.market_commentary && <p className="text-muted-foreground">{report.market_commentary}</p>}
        </CardContent>
      </Card>
      {picks.map((t) => <ThesisCard key={t.ticker} thesis={t} />)}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}
