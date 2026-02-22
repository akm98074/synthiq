"use client";

import { useState, useRef } from "react";
import { Upload, Link2, X, FileText, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { sourcesApi } from "@/lib/api-client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@clerk/nextjs";
import { setAuthToken } from "@/lib/api-client";

function useSetAuth() {
  const { getToken } = useAuth();
  useState(() => {
    getToken().then((t) => setAuthToken(t));
  });
}

export default function IngestPage({ params }: { params: { id: string } }) {
  useSetAuth();
  const queryClient = useQueryClient();
  const [urlInput, setUrlInput] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ["sources", params.id],
    queryFn: () => sourcesApi.list(params.id),
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => sourcesApi.uploadFile(params.id, file),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["sources", params.id] }),
  });

  const urlMutation = useMutation({
    mutationFn: (url: string) => sourcesApi.addUrl(params.id, url),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["sources", params.id] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (sourceId: string) => sourcesApi.delete(params.id, sourceId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["sources", params.id] }),
  });

  function handleFiles(files: FileList | null) {
    if (!files) return;
    Array.from(files).forEach((f) => uploadMutation.mutate(f));
  }

  function handleUrlAdd() {
    const url = urlInput.trim();
    if (!url) return;
    urlMutation.mutate(url);
    setUrlInput("");
  }

  return (
    <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Ingest Sources</h2>
        <p className="text-slate-500 text-sm mt-1">
          Add up to 50 sources — PDFs, URLs, DOCX, or plain text files.
        </p>
      </div>

      {/* Drop zone */}
      <div
        className={`border-2 border-dashed rounded-xl p-10 text-center transition-colors cursor-pointer ${
          dragOver
            ? "border-indigo-400 bg-indigo-50"
            : "border-slate-300 hover:border-indigo-300 hover:bg-slate-50"
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          handleFiles(e.dataTransfer.files);
        }}
        onClick={() => fileRef.current?.click()}
      >
        <Upload className="w-10 h-10 text-slate-400 mx-auto mb-3" />
        <p className="font-medium text-slate-700">
          Drop files here or click to browse
        </p>
        <p className="text-sm text-slate-400 mt-1">
          PDF, DOCX, TXT — up to 100 pages per source
        </p>
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          multiple
          accept=".pdf,.docx,.txt"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {/* URL input */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Link2 className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <Input
            className="pl-9"
            placeholder="Paste a URL to add as a source"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleUrlAdd()}
          />
        </div>
        <Button
          variant="outline"
          onClick={handleUrlAdd}
          disabled={!urlInput.trim() || urlMutation.isPending}
        >
          Add URL
        </Button>
      </div>

      {/* Source list */}
      {(isLoading || sources.length > 0) && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-slate-700">
              Sources ({sources.length}/50)
            </h3>
          </div>
          <div className="space-y-2">
            {isLoading && (
              <div className="h-12 rounded-lg bg-slate-200 animate-pulse" />
            )}
            {sources.map((source) => (
              <div
                key={source.id}
                className="flex items-center gap-3 px-4 py-3 bg-white border rounded-lg"
              >
                {source.type === "url" ? (
                  <Globe className="w-4 h-4 text-indigo-500 shrink-0" />
                ) : (
                  <FileText className="w-4 h-4 text-indigo-500 shrink-0" />
                )}
                <span className="flex-1 text-sm text-slate-700 truncate">
                  {source.url ?? source.filename}
                </span>
                <Badge
                  variant={
                    source.status === "ready"
                      ? "default"
                      : source.status === "error"
                      ? "destructive"
                      : "secondary"
                  }
                  className="text-xs"
                >
                  {source.status}
                </Badge>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-slate-400 hover:text-red-500"
                  onClick={() => deleteMutation.mutate(source.id)}
                >
                  <X className="w-3.5 h-3.5" />
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
