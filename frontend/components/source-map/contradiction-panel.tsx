"use client";

import { ContradictionData } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle } from "lucide-react";

interface ContradictionPanelProps {
  contradictions: ContradictionData[];
}

function SignificanceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.7
      ? "bg-red-100 text-red-700"
      : value >= 0.4
      ? "bg-amber-100 text-amber-700"
      : "bg-slate-100 text-slate-600";
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${color}`}>
      {pct}% significance
    </span>
  );
}

export function ContradictionPanel({ contradictions }: ContradictionPanelProps) {
  if (contradictions.length === 0) return null;

  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <AlertTriangle className="w-5 h-5 text-amber-500" />
        <h2 className="text-lg font-semibold text-slate-900">Contradictions</h2>
        <Badge variant="secondary">{contradictions.length}</Badge>
      </div>
      <div className="space-y-4">
        {contradictions.map((c) => (
          <div
            key={c.id}
            className="border rounded-xl overflow-hidden bg-white shadow-sm"
          >
            <div className="flex items-center justify-between px-4 py-2 bg-amber-50 border-b">
              <div>
                <span className="text-xs text-amber-600 font-medium uppercase tracking-wide">
                  {c.entity}
                </span>
                <p className="text-sm font-medium text-amber-900">{c.claim}</p>
              </div>
              <SignificanceBadge value={c.significance} />
            </div>
            <div className="grid grid-cols-2 divide-x">
              <div className="p-4">
                <p className="text-xs font-semibold text-slate-500 mb-1 truncate">
                  {c.source_a}
                </p>
                <p className="text-sm text-slate-700 italic">
                  &ldquo;{c.quote_a}&rdquo;
                </p>
              </div>
              <div className="p-4">
                <p className="text-xs font-semibold text-slate-500 mb-1 truncate">
                  {c.source_b}
                </p>
                <p className="text-sm text-slate-700 italic">
                  &ldquo;{c.quote_b}&rdquo;
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
