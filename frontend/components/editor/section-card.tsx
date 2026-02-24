"use client";

import { RefreshCw, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CitationTooltip } from "./citation-tooltip";
import { InstructionBar } from "./instruction-bar";
import { SectionData } from "@/lib/api-client";

interface SectionCardProps {
  section: SectionData;
  isActive: boolean;
  isRegenerating: boolean;
  isInstructing: boolean;
  onClick: () => void;
  onRegenerate: (sectionId: string) => void;
  onInstruct: (sectionId: string, instruction: string) => void;
}

export function SectionCard({
  section,
  isActive,
  isRegenerating,
  isInstructing,
  onClick,
  onRegenerate,
  onInstruct,
}: SectionCardProps) {
  const isGenerating = section.status === "generating";
  const isError = section.status === "error";

  return (
    <article
      id={`section-${section.id}`}
      className={`bg-white border rounded-xl p-6 space-y-4 transition-shadow cursor-pointer ${
        isActive ? "ring-2 ring-indigo-200 shadow-md" : "hover:shadow-sm"
      }`}
      onClick={onClick}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-lg font-semibold text-slate-900 leading-snug">
          {section.title}
        </h3>
        <Button
          variant="ghost"
          size="sm"
          className="text-xs text-slate-400 hover:text-slate-700 gap-1 shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            onRegenerate(section.id);
          }}
          disabled={isRegenerating || isGenerating}
        >
          {isRegenerating ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <RefreshCw className="w-3 h-3" />
          )}
          Regenerate
        </Button>
      </div>

      {/* Content */}
      {isGenerating ? (
        <div className="flex items-center gap-2 py-6 text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span className="text-sm">Writing section…</span>
        </div>
      ) : isError ? (
        <div className="py-4 text-sm text-red-500">
          Generation failed for this section.
        </div>
      ) : (
        <div
          className="prose prose-sm max-w-none text-slate-700 leading-relaxed
            prose-headings:font-semibold prose-headings:text-slate-800
            prose-strong:text-slate-900
            [&_.citation-marker]:text-indigo-600 [&_.citation-marker]:font-medium
            [&_.citation-marker]:text-xs [&_.citation-marker]:cursor-pointer
            [&_.citation-marker:hover]:underline"
          dangerouslySetInnerHTML={{ __html: section.content }}
        />
      )}

      {/* Citations */}
      <CitationTooltip citations={section.citations} />

      {/* Instruction bar — only when section is active */}
      {isActive && !isGenerating && (
        <InstructionBar
          sectionId={section.id}
          isPending={isInstructing}
          onSubmit={onInstruct}
        />
      )}
    </article>
  );
}
