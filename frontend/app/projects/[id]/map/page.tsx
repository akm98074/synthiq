"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { projectsApi } from "@/lib/api-client";
import { useSourceMap, useFlagSource } from "@/lib/hooks/use-source-map";
import { ClusterGrid } from "@/components/source-map/cluster-grid";
import { ContradictionPanel } from "@/components/source-map/contradiction-panel";
import { GapPanel } from "@/components/source-map/gap-panel";
import { SourceSidebar } from "@/components/source-map/source-sidebar";
import { Badge } from "@/components/ui/badge";
import { Loader2, Network } from "lucide-react";

const STATUS_LABEL: Record<string, string> = {
  created: "Waiting for sources",
  ingesting: "Ingesting sources…",
  indexing: "Clustering sources…",
  cross_referencing: "Detecting contradictions & gaps…",
  generating: "Generating deliverable…",
  ready: "Analysis complete",
  error: "Processing error",
};

function ProcessingBanner({ status }: { status: string }) {
  const isTerminal = status === "ready" || status === "error";
  const label = STATUS_LABEL[status] ?? status;

  if (isTerminal) return null;

  return (
    <div className="flex items-center gap-3 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-700">
      <Loader2 className="w-4 h-4 animate-spin shrink-0" />
      <span>{label}</span>
      <span className="text-indigo-400 text-xs ml-auto">
        Refreshing automatically…
      </span>
    </div>
  );
}

export default function SourceMapPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(
    null
  );

  // Project status drives polling
  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => projectsApi.get(projectId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || status === "ready" || status === "error") return false;
      return 5000;
    },
  });

  const projectStatus = project?.status ?? "created";

  const {
    data: sourceMap,
    isLoading: isMapLoading,
    isError: isMapError,
  } = useSourceMap(projectId, projectStatus);

  const { mutate: flagSource, isPending: isFlagging } =
    useFlagSource(projectId);

  const isEmpty =
    !isMapLoading &&
    !isMapError &&
    sourceMap &&
    sourceMap.clusters.length === 0 &&
    sourceMap.contradictions.length === 0 &&
    sourceMap.gaps.length === 0;

  return (
    <div className="max-w-7xl mx-auto px-6 py-10 space-y-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Network className="w-6 h-6 text-indigo-600" />
        <h1 className="text-xl font-semibold text-slate-900">Source Map</h1>
        {sourceMap && sourceMap.entity_count > 0 && (
          <Badge variant="secondary">
            {sourceMap.entity_count} cross-source entities
          </Badge>
        )}
      </div>

      {/* Processing banner */}
      <ProcessingBanner status={projectStatus} />

      {/* Loading skeleton */}
      {isMapLoading && (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-32 rounded-xl bg-slate-200 animate-pulse"
            />
          ))}
        </div>
      )}

      {/* Error */}
      {!isMapLoading && isMapError && (
        <div className="py-20 text-center text-slate-500 text-sm">
          Failed to load source map. Please try again.
        </div>
      )}

      {/* Empty state */}
      {!isMapLoading && isEmpty && (
        <div className="py-20 text-center text-slate-400 text-sm">
          {projectStatus === "ready"
            ? "No analysis data found. Ensure sources were ingested successfully."
            : "Analysis will appear here once sources are processed."}
        </div>
      )}

      {/* Main content */}
      {!isMapLoading && !isMapError && sourceMap && !isEmpty && (
        <div className="flex gap-8">
          {/* Left: clusters + panels */}
          <div className="flex-1 min-w-0 space-y-10">
            <ClusterGrid
              clusters={sourceMap.clusters}
              selectedClusterId={selectedClusterId}
              onSelectCluster={setSelectedClusterId}
            />
            <ContradictionPanel contradictions={sourceMap.contradictions} />
            <GapPanel gaps={sourceMap.gaps} />
          </div>

          {/* Right: source sidebar */}
          <SourceSidebar
            sources={sourceMap.sources}
            selectedClusterId={selectedClusterId}
            onFlag={(sourceId, payload) => flagSource({ sourceId, payload })}
            isPending={isFlagging}
          />
        </div>
      )}
    </div>
  );
}
