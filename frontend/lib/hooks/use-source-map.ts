"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { sourceMapApi, sourcesApi, SourceMapData } from "@/lib/api-client";

export function useSourceMap(projectId: string, projectStatus: string) {
  const isReady = projectStatus === "ready";
  const isProcessing = ["indexing", "cross_referencing"].includes(projectStatus);

  return useQuery<SourceMapData>({
    queryKey: ["source-map", projectId],
    queryFn: () => sourceMapApi.get(projectId),
    enabled: !!projectId,
    // Poll while the pipeline is still running
    refetchInterval: isReady ? false : isProcessing ? 5000 : false,
  });
}

export function useFlagSource(projectId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      sourceId,
      payload,
    }: {
      sourceId: string;
      payload: { is_flagged?: boolean; is_excluded?: boolean };
    }) => sourcesApi.flag(projectId, sourceId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["source-map", projectId] });
    },
  });
}
