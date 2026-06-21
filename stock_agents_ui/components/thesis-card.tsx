import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConvictionBadge } from "@/components/ui/badge";
import type { Thesis } from "@/lib/api";

function ScoreBar({ label, score }: { label: string; score: number }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-24 text-muted-foreground">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div className="h-full bg-accent" style={{ width: `${score * 10}%` }} />
      </div>
      <span className="w-5 text-right font-mono">{score}</span>
    </div>
  );
}

export function ThesisCard({ thesis }: { thesis: Thesis }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <div>
          <CardTitle className="font-mono text-base">
            {thesis.ticker} <span className="text-muted-foreground">{thesis.name}</span>
          </CardTitle>
        </div>
        <ConvictionBadge score={thesis.conviction_score} />
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm leading-relaxed text-muted-foreground">{thesis.one_paragraph_summary}</p>

        <div className="flex flex-col gap-1.5">
          <ScoreBar label="Fundamentals" score={thesis.fundamentals_score} />
          <ScoreBar label="Balance sheet" score={thesis.balance_sheet_score} />
          <ScoreBar label="Management" score={thesis.management_score} />
          <ScoreBar label="Stress test" score={thesis.stress_test_score} />
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-emerald-400">Bull case</div>
            <ul className="list-disc pl-4 text-sm">
              {thesis.bull_case.map((b, i) => <li key={i}>{b}</li>)}
            </ul>
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-rose-400">Bear case</div>
            <ul className="list-disc pl-4 text-sm">
              {thesis.bear_case.map((b, i) => <li key={i}>{b}</li>)}
            </ul>
          </div>
        </div>

        {(thesis.peer_preference_strength != null || thesis.macro_fit || thesis.forensic_risk_score != null) && (
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
            {thesis.peer_preference_strength != null && (
              <span>Peer preference: <span className="font-mono">{thesis.peer_preference_strength}/10</span></span>
            )}
            {thesis.forensic_risk_score != null && (
              <span>
                Forensic risk:{" "}
                <span className={
                  thesis.forensic_risk_score >= 7 ? "font-mono text-rose-400"
                  : thesis.forensic_risk_score >= 4 ? "font-mono text-amber-400"
                  : "font-mono text-emerald-400"
                }>
                  {thesis.forensic_risk_score}/10
                </span>
              </span>
            )}
            {thesis.macro_fit && <span>Macro fit: {thesis.macro_fit}</span>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
