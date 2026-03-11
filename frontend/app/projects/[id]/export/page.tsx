"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import {
  Download,
  FileText,
  FileType2,
  AlertCircle,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { CitationStyle, ExportFormat } from "@/lib/api-client";
import { useExport } from "@/lib/hooks/use-export";

// ─── Reusable controls ────────────────────────────────────────────────────────

function ToggleGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string; icon?: React.ReactNode }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
        {label}
      </p>
      <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
        {options.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-sm font-medium transition-all ${
              value === opt.value
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {opt.icon}
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Checkbox({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer group">
      <div className="mt-0.5 shrink-0">
        <input
          type="checkbox"
          className="sr-only"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <div
          className={`w-4 h-4 rounded border-2 flex items-center justify-center transition-colors ${
            checked
              ? "bg-indigo-600 border-indigo-600"
              : "bg-white border-slate-300 group-hover:border-slate-400"
          }`}
        >
          {checked && (
            <svg
              className="w-2.5 h-2.5 text-white"
              fill="none"
              viewBox="0 0 12 12"
              aria-hidden="true"
            >
              <path
                d="M2 6l3 3 5-5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </div>
      </div>
      <div>
        <p className="text-sm font-medium text-slate-800 leading-snug">{label}</p>
        <p className="text-xs text-slate-500 mt-0.5">{description}</p>
      </div>
    </label>
  );
}

// ─── Page ──────────────────────────────────────────────────────────────────────

export default function ExportPage() {
  const { id: projectId } = useParams<{ id: string }>();

  const [format, setFormat] = useState<ExportFormat>("docx");
  const [citationStyle, setCitationStyle] = useState<CitationStyle>("inline");
  const [includeSourceMap, setIncludeSourceMap] = useState(false);

  const { trigger, isPending, result, error, reset } = useExport(projectId);

  function handleGenerate() {
    reset();
    trigger({
      format,
      citation_style: citationStyle,
      include_source_map: includeSourceMap,
    });
  }

  return (
    <div className="max-w-2xl mx-auto px-6 py-10">
      <div className="mb-8">
        <h2 className="text-xl font-semibold text-slate-900 mb-1">
          Export deliverable
        </h2>
        <p className="text-sm text-slate-500">
          Download your research deliverable as a formatted document.
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-2xl divide-y divide-slate-100 shadow-sm">
        {/* Format selector */}
        <div className="px-6 py-5 space-y-2">
          <ToggleGroup<ExportFormat>
            label="Format"
            value={format}
            onChange={(v) => {
              setFormat(v);
              reset();
            }}
            options={[
              {
                value: "docx",
                label: "Word (.docx)",
                icon: <FileText className="w-3.5 h-3.5" />,
              },
              {
                value: "pdf",
                label: "PDF",
                icon: <FileType2 className="w-3.5 h-3.5" />,
              },
            ]}
          />
          <p className="text-xs text-slate-400">
            {format === "docx"
              ? "Fully editable Word document with styled headings, paragraphs, and tables."
              : "Print-ready PDF with embedded fonts, page numbers, and a styled layout."}
          </p>
        </div>

        {/* Citation style */}
        <div className="px-6 py-5 space-y-2">
          <ToggleGroup<CitationStyle>
            label="Citation style"
            value={citationStyle}
            onChange={(v) => {
              setCitationStyle(v);
              reset();
            }}
            options={[
              { value: "inline", label: "Inline  [Source N]" },
              { value: "footnotes", label: "Footnotes  [1]" },
            ]}
          />
          <p className="text-xs text-slate-400">
            {citationStyle === "inline"
              ? "Source markers appear inline as [Source N, p.X] throughout the text."
              : "Markers replaced with superscript numbers; full references listed after each section."}
          </p>
        </div>

        {/* Appendix option */}
        <div className="px-6 py-5">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
            Appendix
          </p>
          <Checkbox
            label="Include Source Map"
            description="Appends a structured table of topic clusters, contradictions detected between sources, and research gaps at the end of the document."
            checked={includeSourceMap}
            onChange={(v) => {
              setIncludeSourceMap(v);
              reset();
            }}
          />
        </div>

        {/* Download section */}
        <div className="px-6 py-5">
          {result ? (
            /* Success state */
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm text-green-700">
                <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
                <span>
                  <strong>{result.filename}</strong> is ready to download.
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                <a
                  href={result.download_url}
                  download={result.filename}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                  Download {result.format.toUpperCase()}
                </a>
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={handleGenerate}
                  disabled={isPending}
                >
                  {isPending ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    "Regenerate"
                  )}
                </Button>
              </div>
            </div>
          ) : error ? (
            /* Error state */
            <div className="space-y-3">
              <div className="flex items-start gap-2 text-sm text-red-600">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleGenerate}
                disabled={isPending}
              >
                Try again
              </Button>
            </div>
          ) : (
            /* Default CTA */
            <Button
              className="bg-indigo-600 hover:bg-indigo-700 text-white gap-2"
              onClick={handleGenerate}
              disabled={isPending}
            >
              {isPending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Building document…
                </>
              ) : (
                <>
                  <Download className="w-4 h-4" />
                  Generate &amp; download
                </>
              )}
            </Button>
          )}
        </div>
      </div>

      <p className="mt-4 text-xs text-slate-400 text-center">
        Download links are valid for 1 hour. Regenerate to get a fresh link.
      </p>
    </div>
  );
}
