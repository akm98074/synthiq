"use client";

import { SourceSidebarData } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Flag, EyeOff, FileText, Globe, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";

interface SourceSidebarProps {
  sources: SourceSidebarData[];
  selectedClusterId: string | null;
  onFlag: (sourceId: string, payload: { is_flagged?: boolean; is_excluded?: boolean }) => void;
  isPending: boolean;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "ready") return <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />;
  if (status === "error") return <AlertCircle className="w-3.5 h-3.5 text-red-400" />;
  if (status === "processing") return <Loader2 className="w-3.5 h-3.5 text-indigo-400 animate-spin" />;
  return <div className="w-3.5 h-3.5 rounded-full bg-slate-300" />;
}

export function SourceSidebar({
  sources,
  selectedClusterId,
  onFlag,
  isPending,
}: SourceSidebarProps) {
  const filtered =
    selectedClusterId
      ? sources.filter((s) => s.cluster_ids.includes(selectedClusterId))
      : sources;

  return (
    <aside className="w-72 shrink-0 flex flex-col gap-2">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-slate-700">
          Sources
          {selectedClusterId ? " (filtered)" : ""}
        </h3>
        <span className="text-xs text-slate-400">{filtered.length}</span>
      </div>

      {filtered.length === 0 ? (
        <p className="text-xs text-slate-400 text-center py-6">
          No sources{selectedClusterId ? " in this cluster" : ""}.
        </p>
      ) : (
        filtered.map((source) => (
          <div
            key={source.id}
            className={`rounded-lg border p-3 bg-white space-y-2 transition-opacity ${
              source.is_excluded ? "opacity-40" : ""
            }`}
          >
            <div className="flex items-start gap-2">
              {source.type === "url" ? (
                <Globe className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
              ) : (
                <FileText className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-slate-800 truncate">
                  {source.filename ?? source.url ?? source.id}
                </p>
                <div className="flex items-center gap-1 mt-0.5">
                  <StatusIcon status={source.status} />
                  {source.confidence_score !== undefined && (
                    <span className="text-xs text-slate-400">
                      {Math.round(source.confidence_score * 100)}% confidence
                    </span>
                  )}
                </div>
              </div>
            </div>

            {source.is_flagged && (
              <Badge variant="outline" className="text-xs text-amber-600 border-amber-300 bg-amber-50">
                Flagged for review
              </Badge>
            )}

            <div className="flex gap-1">
              <Button
                size="sm"
                variant={source.is_flagged ? "default" : "outline"}
                className="h-6 text-xs px-2 flex-1"
                disabled={isPending}
                onClick={() =>
                  onFlag(source.id, { is_flagged: !source.is_flagged })
                }
              >
                <Flag className="w-3 h-3 mr-1" />
                {source.is_flagged ? "Unflag" : "Flag"}
              </Button>
              <Button
                size="sm"
                variant={source.is_excluded ? "default" : "outline"}
                className="h-6 text-xs px-2 flex-1"
                disabled={isPending}
                onClick={() =>
                  onFlag(source.id, { is_excluded: !source.is_excluded })
                }
              >
                <EyeOff className="w-3 h-3 mr-1" />
                {source.is_excluded ? "Include" : "Exclude"}
              </Button>
            </div>
          </div>
        ))
      )}
    </aside>
  );
}
