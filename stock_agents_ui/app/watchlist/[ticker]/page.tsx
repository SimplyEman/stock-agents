"use client";

import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ConvictionBadge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ConvictionChart } from "@/components/conviction-chart";
import { ThesisCard } from "@/components/thesis-card";
import { FalsifierList } from "@/components/falsifier-list";
import { del, fetcher, post, type Snapshot, type ThesisSnapshot } from "@/lib/api";

export default function TickerDetail() {
  const ticker = String(useParams().ticker).toUpperCase();
  const router = useRouter();
  const history = useSWR<Snapshot[]>(`/api/watchlist/${ticker}/history`, fetcher);
  const latestId = history.data?.[history.data.length - 1]?.id;
  const snap = useSWR<ThesisSnapshot>(latestId ? `/api/thesis/${latestId}` : null, fetcher);

  async function refresh() { await post(`/api/watchlist/${ticker}/refresh`); router.push("/runs"); }
  async function untrack() { await del(`/api/watchlist/${ticker}`); router.push("/watchlist"); }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="font-mono text-xl font-semibold">{ticker}</h1>
          {snap.data && <ConvictionBadge score={snap.data.thesis.conviction_score} />}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={refresh}>Refresh now</Button>
          <Button variant="ghost" onClick={untrack}>Untrack</Button>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>Conviction trend</CardTitle></CardHeader>
        <CardContent>
          {!history.data ? <Skeleton className="h-[220px] w-full" /> : <ConvictionChart snapshots={history.data} />}
        </CardContent>
      </Card>

      {snap.data ? (
        <ThesisCard thesis={snap.data.thesis} />
      ) : (
        <Skeleton className="h-64 w-full" />
      )}

      {snap.data && (
        <Card>
          <CardHeader><CardTitle>What would change my mind</CardTitle></CardHeader>
          <CardContent><FalsifierList text={snap.data.thesis.what_would_change_my_mind} /></CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Snapshot history</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-1.5">
          {history.data?.slice().reverse().map((s) => (
            <div key={s.id} className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{s.taken_at.slice(0, 19).replace("T", " ")}</span>
              <span className="font-mono">{s.conviction.toFixed(1)}</span>
            </div>
          ))}
          {history.data?.length === 0 && <p className="text-sm text-muted-foreground">No snapshots.</p>}
        </CardContent>
      </Card>
    </div>
  );
}
