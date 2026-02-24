"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deliverableApi, DeliverableData } from "@/lib/api-client";

const API_URL =
  typeof process !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
    : "http://localhost:8000";

// ─── Polling query ────────────────────────────────────────────────────────────

export function useDeliverable(projectId: string) {
  return useQuery<DeliverableData>({
    queryKey: ["deliverable", projectId],
    queryFn: () => deliverableApi.get(projectId),
    retry: false,
  });
}

// ─── SSE progressive stream ────────────────────────────────────────────────

export function useDeliverableSSE(
  projectId: string,
  enabled: boolean,
  authToken: string | null | undefined
) {
  const queryClient = useQueryClient();
  const esRef = useRef<EventSource | null>(null);
  const [streaming, setStreaming] = useState(false);

  const start = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
    }

    const url = `${API_URL}/projects/${projectId}/deliverable/events${
      authToken ? `?token=${encodeURIComponent(authToken)}` : ""
    }`;

    // Attach auth via query param since EventSource doesn't support headers
    const es = new EventSource(url);
    esRef.current = es;
    setStreaming(true);

    es.addEventListener("progress", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as DeliverableData;
        queryClient.setQueryData(["deliverable", projectId], data);
      } catch {
        // ignore parse errors
      }
    });

    es.addEventListener("done", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as { status: string };
        // Final refresh from server
        queryClient.invalidateQueries({ queryKey: ["deliverable", projectId] });
      } catch {
        // ignore
      }
      setStreaming(false);
      es.close();
      esRef.current = null;
    });

    es.addEventListener("error", () => {
      setStreaming(false);
      es.close();
      esRef.current = null;
      // Fall back to polling
      queryClient.invalidateQueries({ queryKey: ["deliverable", projectId] });
    });
  }, [projectId, authToken, queryClient]);

  const stop = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    setStreaming(false);
  }, []);

  useEffect(() => {
    if (enabled) {
      start();
    }
    return () => {
      esRef.current?.close();
      esRef.current = null;
    };
  }, [enabled, start]);

  return { streaming, start, stop };
}

// ─── Mutations ────────────────────────────────────────────────────────────────

export function useGenerateDeliverable(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => deliverableApi.generate(projectId),
    onSuccess: (data) => {
      queryClient.setQueryData(["deliverable", projectId], data);
    },
  });
}

export function useRegenerateSection(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sectionId: string) =>
      deliverableApi.regenerateSection(projectId, sectionId),
    onSuccess: (data) => {
      queryClient.setQueryData(["deliverable", projectId], data);
    },
  });
}

export function useInstructSection(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      sectionId,
      instruction,
    }: {
      sectionId: string;
      instruction: string;
    }) => deliverableApi.instructSection(projectId, sectionId, instruction),
    onSuccess: (data) => {
      queryClient.setQueryData(["deliverable", projectId], data);
    },
  });
}
