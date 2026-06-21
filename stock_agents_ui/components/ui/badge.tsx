import * as React from "react";
import { cn } from "@/lib/utils";
import { convictionClasses, convictionLabel } from "@/lib/utils";

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
        className,
      )}
      {...props}
    />
  );
}

export function ConvictionBadge({ score }: { score: number | null | undefined }) {
  return (
    <Badge className={cn("font-mono", convictionClasses(score))}>
      {score == null ? "—" : score.toFixed(1)} · {convictionLabel(score)}
    </Badge>
  );
}
