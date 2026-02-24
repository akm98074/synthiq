"use client";

import { CitationData } from "@/lib/api-client";

interface CitationTooltipProps {
  citations: CitationData[];
}

/**
 * Renders a row of citation badges at the bottom of a section.
 * Each badge shows the source title and optional page.
 * Hover reveals an excerpt from the source chunk (if available).
 */
export function CitationTooltip({ citations }: CitationTooltipProps) {
  if (!citations || citations.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 pt-3 border-t border-slate-100">
      {citations.map((citation, idx) => (
        <div key={idx} className="group relative">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-100 cursor-default select-none">
            {citation.source_title}
            {citation.page ? `, p.${citation.page}` : ""}
          </span>

          {citation.quote && (
            <div className="pointer-events-none absolute bottom-full mb-1.5 left-0 z-50 w-72 hidden group-hover:block">
              <div className="bg-slate-900 text-slate-100 text-xs rounded-lg px-3 py-2 shadow-xl leading-relaxed">
                <p className="font-semibold text-slate-300 mb-1">
                  {citation.source_title}
                  {citation.page ? `, p.${citation.page}` : ""}
                </p>
                <p className="line-clamp-4 italic">&ldquo;{citation.quote}&rdquo;</p>
              </div>
              {/* Arrow */}
              <div className="w-2 h-2 bg-slate-900 rotate-45 ml-3 -mt-1" />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
