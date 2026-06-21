"use client";

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, THead, TR, TH, TD } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { fetcher, type Run } from "@/lib/api";

export default function RunsPage() {
  const { data } = useSWR<Run[]>("/api/runs?limit=100", fetcher, { refreshInterval: 5000 });
  const router = useRouter();

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold tracking-tight">Runs</h1>
      <Card>
        <CardContent className="p-0">
          {!data && <Skeleton className="m-5 h-40" />}
          {data && (
            <Table>
              <THead>
                <TR className="hover:bg-transparent">
                  <TH>Started</TH><TH>Kind</TH><TH>Target</TH><TH>Status</TH>
                  <TH className="text-right">Cost</TH>
                </TR>
              </THead>
              <tbody>
                {data.map((r) => (
                  <TR key={r.id} className="cursor-pointer" onClick={() => router.push(`/runs/${r.id}`)}>
                    <TD className="text-muted-foreground">{r.started_at.slice(0, 19).replace("T", " ")}</TD>
                    <TD>{r.kind}</TD>
                    <TD className="font-mono">{r.ticker || r.theme || "—"}</TD>
                    <TD className={cn(
                      r.status === "success" && "text-emerald-400",
                      r.status === "failed" && "text-rose-400",
                      r.status === "running" && "text-amber-400",
                    )}>{r.status}</TD>
                    <TD className="text-right font-mono">{r.cost_estimate_usd != null ? `$${r.cost_estimate_usd.toFixed(2)}` : "—"}</TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
