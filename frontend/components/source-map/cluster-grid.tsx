"use client";

import { ClusterData } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Layers } from "lucide-react";

interface ClusterGridProps {
  clusters: ClusterData[];
  selectedClusterId: string | null;
  onSelectCluster: (id: string | null) => void;
}

export function ClusterGrid({
  clusters,
  selectedClusterId,
  onSelectCluster,
}: ClusterGridProps) {
  if (clusters.length === 0) {
    return (
      <div className="text-center py-12 text-slate-400 text-sm">
        No clusters yet. Ingest and process sources to see theme clusters.
      </div>
    );
  }

  return (
    <section>
      <div className="flex items-center gap-2 mb-4">
        <Layers className="w-5 h-5 text-indigo-600" />
        <h2 className="text-lg font-semibold text-slate-900">Theme Clusters</h2>
        <Badge variant="secondary">{clusters.length}</Badge>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {clusters.map((cluster) => {
          const isSelected = cluster.id === selectedClusterId;
          return (
            <button
              key={cluster.id}
              onClick={() =>
                onSelectCluster(isSelected ? null : cluster.id)
              }
              className="text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 rounded-xl"
            >
              <Card
                className={`transition-all border-2 ${
                  isSelected
                    ? "border-indigo-500 shadow-md"
                    : "border-transparent hover:border-slate-200"
                }`}
              >
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{cluster.label}</CardTitle>
                  <p className="text-xs text-slate-500">
                    {cluster.source_count} source
                    {cluster.source_count !== 1 ? "s" : ""} ·{" "}
                    {cluster.chunk_count} chunk
                    {cluster.chunk_count !== 1 ? "s" : ""}
                  </p>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1">
                    {cluster.key_entities.slice(0, 5).map((entity) => (
                      <Badge
                        key={entity}
                        variant="outline"
                        className="text-xs capitalize"
                      >
                        {entity}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </button>
          );
        })}
      </div>
    </section>
  );
}
