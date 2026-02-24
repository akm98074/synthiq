"use client";

import { useRef, useState } from "react";
import { Upload, FileText, CheckCircle2, AlertCircle, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useUploadVoiceSample, useDeleteVoiceProfile } from "@/lib/hooks/use-voice";
import { VoiceProfile } from "@/lib/api-client";

const MAX_SAMPLES = 5;
const ACCEPT = ".pdf,.docx,.txt";

interface SampleUploaderProps {
  profile: VoiceProfile | null | undefined;
}

interface UploadStatus {
  name: string;
  state: "uploading" | "done" | "error";
  error?: string;
}

export function SampleUploader({ profile }: SampleUploaderProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploads, setUploads] = useState<UploadStatus[]>([]);

  const uploadMutation = useUploadVoiceSample();
  const deleteMutation = useDeleteVoiceProfile();

  const sampleCount = profile?.sample_count ?? 0;
  const canUpload = sampleCount < MAX_SAMPLES;

  async function handleFiles(files: FileList | null) {
    if (!files || !canUpload) return;
    const allowed = Array.from(files).slice(0, MAX_SAMPLES - sampleCount);

    for (const file of allowed) {
      setUploads((prev) => [...prev, { name: file.name, state: "uploading" }]);
      try {
        await uploadMutation.mutateAsync(file);
        setUploads((prev) =>
          prev.map((u) =>
            u.name === file.name && u.state === "uploading"
              ? { ...u, state: "done" }
              : u
          )
        );
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "Upload failed";
        setUploads((prev) =>
          prev.map((u) =>
            u.name === file.name && u.state === "uploading"
              ? { ...u, state: "error", error: msg }
              : u
          )
        );
      }
    }
  }

  return (
    <div className="space-y-4">
      {/* Drop zone */}
      {canUpload ? (
        <div
          className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer ${
            dragOver
              ? "border-indigo-400 bg-indigo-50"
              : "border-slate-300 hover:border-indigo-300 hover:bg-slate-50"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            handleFiles(e.dataTransfer.files);
          }}
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="w-8 h-8 text-slate-400 mx-auto mb-2" />
          <p className="font-medium text-slate-700 text-sm">
            Drop writing samples here or click to browse
          </p>
          <p className="text-xs text-slate-400 mt-1">
            PDF, DOCX, or TXT · Up to {MAX_SAMPLES} samples total ·{" "}
            {MAX_SAMPLES - sampleCount} remaining
          </p>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            multiple
            accept={ACCEPT}
            onChange={(e) => handleFiles(e.target.files)}
          />
        </div>
      ) : (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-center text-sm text-indigo-700">
          Maximum {MAX_SAMPLES} samples reached. Delete your profile to start over.
        </div>
      )}

      {/* Per-file upload status */}
      {uploads.length > 0 && (
        <div className="space-y-1.5">
          {uploads.map((u, i) => (
            <div
              key={i}
              className="flex items-center gap-2 text-sm px-3 py-2 rounded-lg bg-slate-50 border"
            >
              <FileText className="w-4 h-4 text-slate-400 shrink-0" />
              <span className="flex-1 truncate text-slate-700">{u.name}</span>
              {u.state === "uploading" && (
                <Loader2 className="w-4 h-4 text-indigo-500 animate-spin shrink-0" />
              )}
              {u.state === "done" && (
                <CheckCircle2 className="w-4 h-4 text-green-500 shrink-0" />
              )}
              {u.state === "error" && (
                <span className="text-xs text-red-500 shrink-0">{u.error}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Delete profile */}
      {profile && sampleCount > 0 && (
        <div className="pt-2 flex items-center justify-between border-t">
          <p className="text-xs text-slate-500">
            {sampleCount} sample{sampleCount !== 1 ? "s" : ""} analysed
          </p>
          <Button
            variant="outline"
            size="sm"
            className="text-red-600 border-red-200 hover:bg-red-50 gap-1.5"
            disabled={deleteMutation.isPending}
            onClick={() => {
              deleteMutation.mutate();
              setUploads([]);
            }}
          >
            <Trash2 className="w-3.5 h-3.5" />
            Clear profile
          </Button>
        </div>
      )}
    </div>
  );
}
