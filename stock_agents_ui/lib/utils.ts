import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function convictionLabel(score: number | null | undefined): string {
  if (score == null) return "unknown";
  if (score < 40) return "low";
  if (score < 60) return "medium";
  if (score < 80) return "high";
  return "very high";
}

// Fixed conviction scale (gray / blue / green / dark-green), not rainbow.
export function convictionClasses(score: number | null | undefined): string {
  if (score == null) return "bg-muted text-muted-foreground";
  if (score < 40) return "bg-muted text-muted-foreground";
  if (score < 60) return "bg-blue-500/15 text-blue-400";
  if (score < 80) return "bg-emerald-500/15 text-emerald-400";
  return "bg-emerald-600/25 text-emerald-300";
}
