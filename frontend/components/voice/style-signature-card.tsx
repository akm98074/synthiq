"use client";

import { StyleSignature } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface StyleSignatureCardProps {
  signature: StyleSignature;
  sampleCount: number;
}

function LevelBadge({ value }: { value: "low" | "moderate" | "high" }) {
  const colors = {
    low: "bg-slate-100 text-slate-600",
    moderate: "bg-indigo-100 text-indigo-700",
    high: "bg-violet-100 text-violet-700",
  };
  return (
    <span
      className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize ${colors[value]}`}
    >
      {value}
    </span>
  );
}

function StructBadge({ value }: { value: string }) {
  return (
    <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 capitalize">
      {value}
    </span>
  );
}

export function StyleSignatureCard({
  signature,
  sampleCount,
}: StyleSignatureCardProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-slate-800">
            Your Writing Style
          </CardTitle>
          <Badge variant="secondary" className="text-xs">
            {sampleCount} sample{sampleCount !== 1 ? "s" : ""}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-xs text-slate-500 mb-0.5">Avg sentence length</p>
            <p className="font-medium text-slate-800">
              {Math.round(signature.avg_sentence_length)} words
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500 mb-0.5">Avg paragraph length</p>
            <p className="font-medium text-slate-800">
              {Math.round(signature.avg_paragraph_length)} sentences
            </p>
          </div>
          <div>
            <p className="text-xs text-slate-500 mb-1">Hedging language</p>
            <LevelBadge value={signature.hedging_frequency} />
          </div>
          <div>
            <p className="text-xs text-slate-500 mb-1">Technical vocabulary</p>
            <LevelBadge value={signature.technical_vocab_density} />
          </div>
          <div>
            <p className="text-xs text-slate-500 mb-1">Structure</p>
            <StructBadge value={signature.structural_preference} />
          </div>
          <div>
            <p className="text-xs text-slate-500 mb-1">Formality</p>
            <StructBadge value={signature.formality_register} />
          </div>
          <div className="col-span-2">
            <p className="text-xs text-slate-500 mb-1">Section headers</p>
            <StructBadge value={signature.section_header_style} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
