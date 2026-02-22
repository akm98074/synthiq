"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Download, FileText, FileIcon } from "lucide-react";

type ExportFormat = "docx" | "pdf";

interface ExportResponse {
  download_url: string;
}

export default function ExportPage({ params }: { params: { id: string } }) {
  const [format, setFormat] = useState<ExportFormat>("docx");
  const [includeCitations, setIncludeCitations] = useState(true);
  const [includeSourceMap, setIncludeSourceMap] = useState(false);

  const exportMutation = useMutation({
    mutationFn: () =>
      apiClient
        .post<ExportResponse>(`/projects/${params.id}/export`, {
          format,
          include_citations: includeCitations,
          include_source_map: includeSourceMap,
        })
        .then((r) => r.data),
    onSuccess: (data) => {
      window.open(data.download_url, "_blank");
    },
  });

  return (
    <div className="max-w-2xl mx-auto px-6 py-10 space-y-8">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Export</h2>
        <p className="text-slate-500 text-sm mt-1">
          Download your finished deliverable.
        </p>
      </div>

      {/* Format selector */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-slate-700">Format</h3>
        <div className="grid grid-cols-2 gap-3">
          {(["docx", "pdf"] as const).map((f) => {
            const Icon = f === "docx" ? FileText : FileIcon;
            const label = f === "docx" ? "Word Document (.docx)" : "PDF (.pdf)";
            const desc =
              f === "docx"
                ? "Fully editable in Microsoft Word"
                : "Fixed layout, print-ready";
            return (
              <button
                key={f}
                onClick={() => setFormat(f)}
                className={`flex items-start gap-3 p-4 border-2 rounded-xl text-left transition-colors ${
                  format === f
                    ? "border-indigo-500 bg-indigo-50"
                    : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <Icon
                  className={`w-5 h-5 mt-0.5 ${
                    format === f ? "text-indigo-600" : "text-slate-400"
                  }`}
                />
                <div>
                  <div
                    className={`text-sm font-medium ${
                      format === f ? "text-indigo-700" : "text-slate-700"
                    }`}
                  >
                    {label}
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5">{desc}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Options */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-slate-700">Options</h3>
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            className="w-4 h-4 rounded accent-indigo-600"
            checked={includeCitations}
            onChange={(e) => setIncludeCitations(e.target.checked)}
          />
          <div>
            <div className="text-sm text-slate-700">Include inline citations</div>
            <div className="text-xs text-slate-400">
              Every claim linked to source and page number
            </div>
          </div>
        </label>
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            className="w-4 h-4 rounded accent-indigo-600"
            checked={includeSourceMap}
            onChange={(e) => setIncludeSourceMap(e.target.checked)}
          />
          <div>
            <div className="text-sm text-slate-700">
              Append Source Map as PDF appendix
            </div>
            <div className="text-xs text-slate-400">
              Full theme cluster and contradiction summary
            </div>
          </div>
        </label>
      </div>

      {/* Download button */}
      <Button
        size="lg"
        className="w-full bg-indigo-600 hover:bg-indigo-700 text-white gap-2"
        onClick={() => exportMutation.mutate()}
        disabled={exportMutation.isPending}
      >
        <Download className="w-4 h-4" />
        {exportMutation.isPending
          ? "Preparing download..."
          : `Download as ${format.toUpperCase()}`}
      </Button>

      {exportMutation.isError && (
        <p className="text-sm text-red-500 text-center">
          Export failed. Please try again.
        </p>
      )}
    </div>
  );
}
