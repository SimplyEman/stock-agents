"use client";

import { useState } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AnalyzeModal } from "@/components/analyze-modal";
import { fetcher, type Theme } from "@/lib/api";

export default function ThemesPage() {
  const { data, mutate } = useSWR<Theme[]>("/api/themes", fetcher);
  const [openFor, setOpenFor] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold tracking-tight">Themes</h1>
      {!data && <Skeleton className="h-40 w-full" />}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {data?.map((t) => (
          <Card key={t.theme}>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle className="font-mono">{t.theme}</CardTitle>
              <Button variant="outline" onClick={() => setOpenFor(t.theme)}>
                Run with filters…
              </Button>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm">
              <div className="text-xs text-muted-foreground">ETFs: {t.etfs.join(", ")}</div>
              <div className="text-xs text-muted-foreground">
                Last analyzed: {t.last_analyzed ? t.last_analyzed.slice(0, 10) : "never"}
              </div>
              {t.top5.length > 0 && (
                <div className="font-mono text-sm">{t.top5.join(" · ")}</div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {openFor && (
        <AnalyzeModal
          initialTheme={openFor}
          onClose={() => { setOpenFor(null); mutate(); }}
        />
      )}
    </div>
  );
}
