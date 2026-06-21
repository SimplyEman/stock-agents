"use client";

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Card, CardContent } from "@/components/ui/card";
import { ConvictionBadge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, THead, TR, TH, TD } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { fetcher, type WatchlistEntry } from "@/lib/api";

export default function WatchlistPage() {
  const { data } = useSWR<WatchlistEntry[]>("/api/watchlist", fetcher);
  const router = useRouter();

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold tracking-tight">Watchlist</h1>
      <Card>
        <CardContent className="p-0">
          {!data && <Skeleton className="m-5 h-40" />}
          {data && (
            <Table>
              <THead>
                <TR className="hover:bg-transparent">
                  <TH>Ticker</TH><TH>Status</TH><TH className="text-right">Entry</TH>
                  <TH className="text-right">Current</TH><TH className="text-right">Δ</TH>
                  <TH>Added</TH>
                </TR>
              </THead>
              <tbody>
                {data.map((w) => (
                  <TR key={w.ticker} className="cursor-pointer"
                    onClick={() => router.push(`/watchlist/${w.ticker}`)}>
                    <TD className="font-mono font-medium">{w.ticker}</TD>
                    <TD className="text-muted-foreground">{w.status}</TD>
                    <TD className="text-right font-mono">{w.entry_conviction.toFixed(1)}</TD>
                    <TD className="text-right">
                      <ConvictionBadge score={w.current_conviction ?? w.entry_conviction} />
                    </TD>
                    <TD className={cn("text-right font-mono", w.delta != null && (w.delta >= 0 ? "text-emerald-400" : "text-rose-400"))}>
                      {w.delta == null ? "—" : `${w.delta >= 0 ? "+" : ""}${w.delta.toFixed(1)}`}
                    </TD>
                    <TD className="text-muted-foreground">{w.added_at.slice(0, 10)}</TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
          {data?.length === 0 && <p className="p-5 text-sm text-muted-foreground">Nothing tracked yet.</p>}
        </CardContent>
      </Card>
    </div>
  );
}
