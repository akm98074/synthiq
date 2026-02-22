"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { RefreshCw, Send, FileText } from "lucide-react";

interface Section {
  id: string;
  title: string;
  content: string;
  citations: { source_id: string; source_title: string; page?: number }[];
}

interface Deliverable {
  id: string;
  version: number;
  sections: Section[];
  status: "generating" | "ready" | "error";
}

export default function DraftPage({ params }: { params: { id: string } }) {
  const queryClient = useQueryClient();
  const [instruction, setInstruction] = useState("");
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);

  const { data: deliverable, isLoading } = useQuery({
    queryKey: ["deliverable", params.id],
    queryFn: () =>
      apiClient
        .get<Deliverable>(`/projects/${params.id}/deliverable`)
        .then((r) => r.data),
    refetchInterval: (query) =>
      query.state.data?.status === "generating" ? 3000 : false,
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      apiClient
        .post(`/projects/${params.id}/deliverable/generate`)
        .then((r) => r.data),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["deliverable", params.id] }),
  });

  const regenerateSectionMutation = useMutation({
    mutationFn: (sectionId: string) =>
      apiClient
        .post(
          `/projects/${params.id}/deliverable/sections/${sectionId}/regenerate`
        )
        .then((r) => r.data),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["deliverable", params.id] }),
  });

  const instructMutation = useMutation({
    mutationFn: ({
      sectionId,
      text,
    }: {
      sectionId: string;
      text: string;
    }) =>
      apiClient
        .post(
          `/projects/${params.id}/deliverable/sections/${sectionId}/instruct`,
          { instruction: text }
        )
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["deliverable", params.id] });
      setInstruction("");
    },
  });

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-10 space-y-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-40 rounded-xl bg-slate-200 animate-pulse" />
        ))}
      </div>
    );
  }

  if (!deliverable) {
    return (
      <div className="max-w-4xl mx-auto px-6 py-20 text-center">
        <FileText className="w-12 h-12 text-slate-300 mx-auto mb-4" />
        <h2 className="text-lg font-semibold text-slate-800 mb-2">
          No draft yet
        </h2>
        <p className="text-slate-500 text-sm mb-6">
          Ingest your sources and build the Source Map, then generate your
          deliverable.
        </p>
        <Button
          className="bg-indigo-600 hover:bg-indigo-700 text-white"
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
        >
          {generateMutation.isPending ? "Starting..." : "Generate draft"}
        </Button>
      </div>
    );
  }

  if (deliverable.status === "generating") {
    return (
      <div className="max-w-4xl mx-auto px-6 py-20 text-center">
        <RefreshCw className="w-8 h-8 text-indigo-500 mx-auto mb-4 animate-spin" />
        <p className="text-slate-600">Generating your deliverable...</p>
      </div>
    );
  }

  return (
    <div className="flex max-w-6xl mx-auto px-6 py-8 gap-6">
      {/* Sidebar: section nav */}
      <aside className="w-48 shrink-0">
        <nav className="space-y-1 sticky top-6">
          {deliverable.sections.map((section) => (
            <button
              key={section.id}
              onClick={() => setActiveSectionId(section.id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                activeSectionId === section.id
                  ? "bg-indigo-50 text-indigo-700 font-medium"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {section.title}
            </button>
          ))}
        </nav>
      </aside>

      {/* Draft content */}
      <div className="flex-1 space-y-8">
        {deliverable.sections.map((section) => (
          <div
            key={section.id}
            id={`section-${section.id}`}
            className="bg-white border rounded-xl p-6 space-y-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-slate-900">
                {section.title}
              </h3>
              <Button
                variant="ghost"
                size="sm"
                className="text-xs text-slate-500 gap-1"
                onClick={() => regenerateSectionMutation.mutate(section.id)}
                disabled={regenerateSectionMutation.isPending}
              >
                <RefreshCw className="w-3 h-3" />
                Regenerate
              </Button>
            </div>

            <div
              className="prose prose-sm max-w-none text-slate-700"
              dangerouslySetInnerHTML={{ __html: section.content }}
            />

            {/* Citations */}
            {section.citations.length > 0 && (
              <div className="flex flex-wrap gap-1 pt-2 border-t">
                {section.citations.map((c, i) => (
                  <Badge
                    key={i}
                    variant="outline"
                    className="text-xs text-slate-500"
                  >
                    {c.source_title}
                    {c.page ? `, p.${c.page}` : ""}
                  </Badge>
                ))}
              </div>
            )}

            {/* Instruction bar */}
            {activeSectionId === section.id && (
              <div className="flex gap-2 pt-2">
                <Input
                  className="text-sm"
                  placeholder='e.g. "Make this more skeptical"'
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && instruction.trim()) {
                      instructMutation.mutate({
                        sectionId: section.id,
                        text: instruction,
                      });
                    }
                  }}
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!instruction.trim() || instructMutation.isPending}
                  onClick={() =>
                    instructMutation.mutate({
                      sectionId: section.id,
                      text: instruction,
                    })
                  }
                >
                  <Send className="w-3.5 h-3.5" />
                </Button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
