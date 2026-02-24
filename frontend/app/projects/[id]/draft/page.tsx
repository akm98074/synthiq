"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useAuth } from "@clerk/nextjs";
import {
  FileText,
  RefreshCw,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { SectionNavigator } from "@/components/editor/section-navigator";
import { SectionCard } from "@/components/editor/section-card";
import {
  useDeliverable,
  useDeliverableSSE,
  useGenerateDeliverable,
  useRegenerateSection,
  useInstructSection,
} from "@/lib/hooks/use-deliverable";

export default function DraftPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const { getToken } = useAuth();
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [authToken, setAuthToken] = useState<string | null>(null);

  // Fetch auth token for SSE connection
  useEffect(() => {
    getToken().then((t) => setAuthToken(t ?? null));
  }, [getToken]);

  const { data: deliverable, isLoading, isError } = useDeliverable(projectId);

  const isGenerating = deliverable?.status === "generating";

  // Stream incremental progress while generating
  useDeliverableSSE(projectId, isGenerating, authToken);

  const generateMutation = useGenerateDeliverable(projectId);
  const regenerateMutation = useRegenerateSection(projectId);
  const instructMutation = useInstructSection(projectId);

  // ─── Loading skeleton ──────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-10 flex gap-6">
        <div className="w-48 shrink-0 space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-8 rounded-lg bg-slate-200 animate-pulse" />
          ))}
        </div>
        <div className="flex-1 space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-48 rounded-xl bg-slate-200 animate-pulse"
            />
          ))}
        </div>
      </div>
    );
  }

  // ─── Error state ───────────────────────────────────────────────────────────
  if (isError) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-20 text-center">
        <AlertCircle className="w-12 h-12 text-red-300 mx-auto mb-4" />
        <h2 className="text-lg font-semibold text-slate-800 mb-2">
          Failed to load draft
        </h2>
        <p className="text-slate-500 text-sm">Refresh the page to try again.</p>
      </div>
    );
  }

  // ─── Empty state — no deliverable yet ─────────────────────────────────────
  if (!deliverable) {
    return (
      <div className="max-w-5xl mx-auto px-6 py-20 text-center">
        <FileText className="w-14 h-14 text-slate-200 mx-auto mb-4" />
        <h2 className="text-xl font-semibold text-slate-800 mb-2">
          No draft yet
        </h2>
        <p className="text-slate-500 text-sm mb-6 max-w-sm mx-auto">
          Once your sources are indexed and the Source Map is built, generate
          your deliverable here.
        </p>
        <Button
          className="bg-indigo-600 hover:bg-indigo-700 text-white"
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
        >
          {generateMutation.isPending ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Starting…
            </>
          ) : (
            "Generate draft"
          )}
        </Button>
      </div>
    );
  }

  // ─── Generating — progressive stream view ─────────────────────────────────
  if (isGenerating) {
    const sections = deliverable.sections ?? [];

    return (
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center gap-3 px-4 py-3 mb-6 bg-indigo-50 border border-indigo-100 rounded-xl text-sm text-indigo-700">
          <Loader2 className="w-4 h-4 animate-spin shrink-0" />
          <span>
            {sections.length === 0
              ? "Analysing sources and building outline…"
              : `Writing section ${sections.length}…`}
          </span>
        </div>

        {sections.length > 0 && (
          <div className="flex gap-6">
            <aside className="w-48 shrink-0">
              <div className="sticky top-6">
                <SectionNavigator
                  sections={sections}
                  activeSectionId={activeSectionId}
                  onSelect={setActiveSectionId}
                />
              </div>
            </aside>
            <div className="flex-1 space-y-6">
              {sections.map((section) => (
                <SectionCard
                  key={section.id}
                  section={section}
                  isActive={activeSectionId === section.id}
                  isRegenerating={false}
                  isInstructing={false}
                  onClick={() => setActiveSectionId(section.id)}
                  onRegenerate={() => {}}
                  onInstruct={() => {}}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ─── Error deliverable ─────────────────────────────────────────────────────
  if (deliverable.status === "error") {
    return (
      <div className="max-w-5xl mx-auto px-6 py-20 text-center">
        <AlertCircle className="w-12 h-12 text-red-300 mx-auto mb-4" />
        <h2 className="text-lg font-semibold text-slate-800 mb-2">
          Generation failed
        </h2>
        <p className="text-slate-500 text-sm mb-6">
          Something went wrong during generation. You can try again.
        </p>
        <Button
          className="bg-indigo-600 hover:bg-indigo-700 text-white"
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
        >
          {generateMutation.isPending ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Starting…
            </>
          ) : (
            "Try again"
          )}
        </Button>
      </div>
    );
  }

  // ─── Ready — full editor view ──────────────────────────────────────────────
  const sections = deliverable.sections ?? [];

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Status bar */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2 text-sm text-slate-600">
          <CheckCircle2 className="w-4 h-4 text-green-500" />
          <span>
            Draft v{deliverable.version} ·{" "}
            {sections.length} section{sections.length !== 1 ? "s" : ""}
          </span>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5 text-xs"
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
        >
          {generateMutation.isPending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5" />
          )}
          Regenerate all
        </Button>
      </div>

      <div className="flex gap-6">
        {/* Section navigator */}
        <aside className="w-48 shrink-0">
          <div className="sticky top-6">
            <SectionNavigator
              sections={sections}
              activeSectionId={activeSectionId}
              onSelect={setActiveSectionId}
            />
          </div>
        </aside>

        {/* Section cards */}
        <div className="flex-1 space-y-6 min-w-0">
          {sections.map((section) => (
            <SectionCard
              key={section.id}
              section={section}
              isActive={activeSectionId === section.id}
              isRegenerating={
                regenerateMutation.isPending &&
                regenerateMutation.variables === section.id
              }
              isInstructing={
                instructMutation.isPending &&
                instructMutation.variables?.sectionId === section.id
              }
              onClick={() => setActiveSectionId(section.id)}
              onRegenerate={(id) => regenerateMutation.mutate(id)}
              onInstruct={(id, instruction) =>
                instructMutation.mutate({ sectionId: id, instruction })
              }
            />
          ))}
        </div>
      </div>
    </div>
  );
}
