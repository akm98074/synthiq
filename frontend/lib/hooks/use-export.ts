"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  CitationStyle,
  ExportFormat,
  ExportResponse,
  exportApi,
} from "@/lib/api-client";

export function useExport(projectId: string) {
  const [result, setResult] = useState<ExportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (payload: {
      format: ExportFormat;
      citation_style: CitationStyle;
      include_source_map: boolean;
    }) => exportApi.export(projectId, payload),
    onSuccess: (data) => {
      setResult(data);
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message || "Export failed");
      setResult(null);
    },
  });

  return {
    trigger: mutation.mutate,
    isPending: mutation.isPending,
    result,
    error,
    reset: () => {
      setResult(null);
      setError(null);
      mutation.reset();
    },
  };
}
