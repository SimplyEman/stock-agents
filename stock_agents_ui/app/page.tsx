"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ConvictionBadge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { AnalyzeModal } from "@/components/analyze-modal";
import { cn } from "@/lib/utils";
import {
  fetcher,
  post,
  type Alert,
  type Run,
  type WatchlistEntry,
} from "@/lib/api";

export default function Dashboard() {
  const wl = useSWR<WatchlistEntry[]>("/api/watchlist", fetcher);
  const alerts = useSWR<Alert[]>("/api/alerts?status=unread", fetcher);
  const runs = useSWR<Run[]>("/api/runs?limit=8", fetcher);
  const [open, setOpen] = useState(false);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <Button onClick={() => setOpen(true)}>Run a theme analysis</Button>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Watchlist</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {!wl.data && <Skeleton className="h-24 w-full" />}
            {wl.data?.length === 0 && <p className="text-sm text-muted-foreground">Nothing tracked yet.</p>}
            {wl.data?.map((w) => (
              <Link key={w.ticker} href={`/watchlist/${w.ticker}`}
                className="flex items-center justify-between rounded-md px-2 py-1.5 hover:bg-muted/50">
                <span className="font-mono text-sm">{w.ticker}</span>
                <div className="flex items-center gap-2">
                  <ConvictionBadge score={w.current_conviction ?? w.entry_conviction} />
                  {w.delta != null && (
                    <span className={cn("font-mono text-xs", w.delta >= 0 ? "text-emerald-400" : "text-rose-400")}>
                      {w.delta >= 0 ? "+" : ""}{w.delta.toFixed(1)}
                    </span>
                  )}
                </div>
              </Link>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Unread alerts</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {!alerts.data && <Skeleton className="h-24 w-full" />}
            {alerts.data?.length === 0 && <p className="text-sm text-muted-foreground">No unread alerts.</p>}
            {alerts.data?.map((a) => (
              <button key={a.id}
                onClick={async () => { await post(`/api/alerts/${a.id}/ack`); alerts.mutate(); }}
                className="flex flex-col items-start rounded-md px-2 py-1.5 text-left hover:bg-muted/50">
                <span className="text-sm">{a.message}</span>
                <span className="text-xs text-muted-foreground">{a.severity} · {a.kind} · click to mark read</span>
              </button>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Recent runs</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {!runs.data && <Skeleton className="h-24 w-full" />}
            {runs.data?.map((r) => (
              <Link key={r.id} href={`/runs/${r.id}`}
                className="flex items-center justify-between rounded-md px-2 py-1.5 hover:bg-muted/50">
                <span className="text-sm">{r.kind}{r.ticker ? ` · ${r.ticker}` : ""}{r.theme ? ` · ${r.theme}` : ""}</span>
                <StatusDot status={r.status} />
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>

      {open && <AnalyzeModal onClose={() => { setOpen(false); runs.mutate(); }} />}
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const color = status === "success" ? "bg-emerald-400" : status === "failed" ? "bg-rose-400" : "bg-amber-400";
  return <span className={cn("h-2 w-2 rounded-full", color)} title={status} />;
}

