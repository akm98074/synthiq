"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { AlertTriangle, Layers, Search } from "lucide-react";

interface SourceMapData {
  clusters: {
    id: string;
    label: string;
    source_count: number;
    key_entities: string[];
  }[];
  contradictions: {
    id: string;
    claim: string;
    source_a: string;
    source_b: string;
    quote_a: string;
    quote_b: string;
  }[];
  gaps: {
    topic: string;
    mentioned_in_count: number;
    missing_in_count: number;
  }[];
}

export default function SourceMapPage({ params }: { params: { id: string } }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["source-map", params.id],
    queryFn: () =>
      apiClient
        .get<SourceMapData>(`/projects/${params.id}/source-map`)
        .then((r) => r.data),
  });

  if (isLoading) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-10 space-y-6">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-32 rounded-xl bg-slate-200 animate-pulse" />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-20 text-center text-slate-500">
        <p>Source map not yet available. Ingest sources first.</p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-10 space-y-10">
      {/* Theme Clusters */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Layers className="w-5 h-5 text-indigo-600" />
          <h2 className="text-lg font-semibold text-slate-900">
            Theme Clusters
          </h2>
          <Badge variant="secondary">{data.clusters.length}</Badge>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {data.clusters.map((cluster) => (
            <Card key={cluster.id}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{cluster.label}</CardTitle>
                <p className="text-xs text-slate-500">
                  {cluster.source_count} source
                  {cluster.source_count !== 1 ? "s" : ""}
                </p>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1">
                  {cluster.key_entities.map((entity) => (
                    <Badge key={entity} variant="outline" className="text-xs">
                      {entity}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Contradictions */}
      {data.contradictions.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle className="w-5 h-5 text-amber-500" />
            <h2 className="text-lg font-semibold text-slate-900">
              Contradictions
            </h2>
            <Badge variant="secondary">{data.contradictions.length}</Badge>
          </div>
          <div className="space-y-4">
            {data.contradictions.map((c) => (
              <div
                key={c.id}
                className="border rounded-xl overflow-hidden bg-white"
              >
                <div className="px-4 py-2 bg-amber-50 border-b text-sm font-medium text-amber-900">
                  {c.claim}
                </div>
                <div className="grid grid-cols-2 divide-x">
                  <div className="p-4">
                    <p className="text-xs font-semibold text-slate-500 mb-1">
                      {c.source_a}
                    </p>
                    <p className="text-sm text-slate-700 italic">
                      &ldquo;{c.quote_a}&rdquo;
                    </p>
                  </div>
                  <div className="p-4">
                    <p className="text-xs font-semibold text-slate-500 mb-1">
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
      )}

      {/* Gaps */}
      {data.gaps.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Search className="w-5 h-5 text-slate-400" />
            <h2 className="text-lg font-semibold text-slate-900">
              Coverage Gaps
            </h2>
            <Badge variant="secondary">{data.gaps.length}</Badge>
          </div>
          <div className="space-y-2">
            {data.gaps.map((gap) => (
              <div
                key={gap.topic}
                className="flex items-center justify-between px-4 py-3 bg-white border rounded-lg"
              >
                <span className="text-sm font-medium text-slate-700">
                  {gap.topic}
                </span>
                <span className="text-xs text-slate-400">
                  Mentioned in {gap.mentioned_in_count} source
                  {gap.mentioned_in_count !== 1 ? "s" : ""}, absent in{" "}
                  {gap.missing_in_count}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
