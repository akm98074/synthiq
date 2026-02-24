"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { SectionData } from "@/lib/api-client";

interface SectionNavigatorProps {
  sections: SectionData[];
  activeSectionId: string | null;
  onSelect: (id: string) => void;
}

export function SectionNavigator({
  sections,
  activeSectionId,
  onSelect,
}: SectionNavigatorProps) {
  function handleClick(id: string) {
    onSelect(id);
    const el = document.getElementById(`section-${id}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  return (
    <nav className="space-y-0.5">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide px-3 mb-2">
        Sections
      </p>
      {sections.map((section, idx) => (
        <button
          key={section.id}
          onClick={() => handleClick(section.id)}
          className={cn(
            "w-full text-left px-3 py-2 rounded-lg text-sm transition-colors flex items-start gap-2",
            activeSectionId === section.id
              ? "bg-indigo-50 text-indigo-700 font-medium"
              : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
          )}
        >
          <span className="shrink-0 mt-0.5 w-4 h-4 rounded-full bg-slate-100 text-slate-500 text-xs flex items-center justify-center font-mono">
            {idx + 1}
          </span>
          <span className="leading-tight">{section.title}</span>
        </button>
      ))}
    </nav>
  );
}
