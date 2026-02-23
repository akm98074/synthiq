"use client";

import { GapData } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Search } from "lucide-react";

interface GapPanelProps {
  gaps: GapData[];
}

export function GapPanel({ gaps }: GapPanelProps) {
  if (gaps.length === 0) return null;

  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <Search className="w-5 h-5 text-slate-400" />
        <h2 className="text-lg font-semibold text-slate-900">Coverage Gaps</h2>
        <Badge variant="secondary">{gaps.length}</Badge>
      </div>
      <div className="space-y-2">
        {gaps.map((gap) => (
          <div
            key={gap.topic}
            className="flex items-center justify-between px-4 py-3 bg-white border rounded-lg hover:bg-slate-50 transition-colors"
          >
            <div>
              <span className="text-sm font-medium text-slate-700 capitalize">
                {gap.topic}
              </span>
            </div>
            <div className="text-right">
              <p className="text-xs text-slate-400">
                Mentioned in{" "}
                <span className="font-medium text-slate-600">
                  {gap.mentioned_in_count}
                </span>{" "}
                source{gap.mentioned_in_count !== 1 ? "s" : ""}
              </p>
              <p className="text-xs text-red-400">
                Absent in{" "}
                <span className="font-medium">{gap.missing_in_count}</span>
              </p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
