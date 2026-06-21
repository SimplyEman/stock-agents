"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { fetcher, post, type Settings } from "@/lib/api";

export default function SettingsPage() {
  const { data, mutate } = useSWR<Settings>("/api/settings", fetcher);
  const [themes, setThemes] = useState("");
  const [channel, setChannel] = useState("pushover");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data) {
      setThemes(data.batch_themes.join(", "));
      setChannel(data.alert_channel);
    }
  }, [data]);

  async function save() {
    await post("/api/settings", {
      batch_themes: themes.split(",").map((t) => t.trim()).filter(Boolean),
      alert_channel: channel,
    });
    setSaved(true);
    mutate();
    setTimeout(() => setSaved(false), 2000);
  }

  if (!data) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold tracking-tight">Settings</h1>

      <Card>
        <CardHeader><CardTitle>API keys (read-only)</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
          {Object.entries(data.keys_configured).map(([k, ok]) => (
            <div key={k} className="flex items-center gap-2">
              <span className={cn("h-2 w-2 rounded-full", ok ? "bg-emerald-400" : "bg-muted-foreground/40")} />
              <span className="capitalize">{k}</span>
              <span className="text-xs text-muted-foreground">{ok ? "configured" : "not set"}</span>
            </div>
          ))}
          <div className="col-span-full text-xs text-muted-foreground">
            Backend: {data.llm_backend}. Keys are edited in the server&apos;s .env, never here.
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Preferences</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Batch themes (comma-separated)</span>
            <input value={themes} onChange={(e) => setThemes(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2 font-mono" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Alert channel</span>
            <select value={channel} onChange={(e) => setChannel(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2">
              <option value="pushover">pushover</option>
              <option value="email">email</option>
              <option value="both">both</option>
            </select>
          </label>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>Weekly budget: ${data.weekly_budget_usd}</span>
            <span>Daily post-earnings: ${data.daily_post_earnings_budget_usd}</span>
            <span>Sunday batch: ${data.sunday_batch_budget_usd}</span>
          </div>
          <div className="flex items-center gap-3">
            <Button onClick={save}>Save</Button>
            {saved && <span className="text-sm text-emerald-400">Saved.</span>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
