"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserButton } from "@clerk/nextjs";
import { ArrowLeft, Mic2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useProject } from "@/lib/hooks/use-projects";
import { useVoiceProfile, useProjectVoiceToggle } from "@/lib/hooks/use-voice";

const TABS = [
  { label: "Ingest", href: (id: string) => `/projects/${id}/ingest` },
  { label: "Source Map", href: (id: string) => `/projects/${id}/map` },
  { label: "Draft", href: (id: string) => `/projects/${id}/draft` },
  { label: "Export", href: (id: string) => `/projects/${id}/export` },
];

export default function ProjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { id: string };
}) {
  const pathname = usePathname();
  const { data: project } = useProject(params.id);
  const { data: voiceProfile } = useVoiceProfile();
  const toggleVoice = useProjectVoiceToggle(params.id);

  const hasVoiceProfile = (voiceProfile?.sample_count ?? 0) > 0;
  const voiceEnabled = project?.use_voice_calibration ?? false;

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      {/* Top nav */}
      <header className="bg-white border-b px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            href="/dashboard"
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Projects
          </Link>
          <span className="text-slate-300">|</span>
          <span className="font-semibold text-slate-900 truncate max-w-xs">
            {project?.name ?? "Loading..."}
          </span>
        </div>
        <div className="flex items-center gap-4">
          {/* Voice calibration toggle — only shown when profile exists */}
          {hasVoiceProfile ? (
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <div className="relative">
                <input
                  type="checkbox"
                  className="sr-only peer"
                  checked={voiceEnabled}
                  disabled={toggleVoice.isPending}
                  onChange={(e) => toggleVoice.mutate(e.target.checked)}
                />
                <div
                  className={cn(
                    "w-9 h-5 rounded-full transition-colors",
                    voiceEnabled ? "bg-indigo-600" : "bg-slate-200"
                  )}
                />
                <div
                  className={cn(
                    "absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform",
                    voiceEnabled ? "translate-x-4" : "translate-x-0"
                  )}
                />
              </div>
              <span className="flex items-center gap-1 text-xs text-slate-600">
                <Mic2 className="w-3.5 h-3.5" />
                Voice
              </span>
            </label>
          ) : (
            <Link
              href="/settings"
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-indigo-600 transition-colors"
            >
              <Mic2 className="w-3.5 h-3.5" />
              Calibrate voice
            </Link>
          )}

          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-indigo-600 flex items-center justify-center">
              <span className="text-white font-bold text-xs">S</span>
            </div>
            <span className="font-semibold text-slate-900 text-sm">Synthiq</span>
          </div>
          <UserButton afterSignOutUrl="/" />
        </div>
      </header>

      {/* Tab bar */}
      <nav className="bg-white border-b px-6">
        <div className="flex gap-0">
          {TABS.map((tab) => {
            const href = tab.href(params.id);
            const isActive = pathname === href;
            return (
              <Link
                key={tab.label}
                href={href}
                className={cn(
                  "px-5 py-3 text-sm font-medium border-b-2 transition-colors",
                  isActive
                    ? "border-indigo-600 text-indigo-600"
                    : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
                )}
              >
                {tab.label}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Page content */}
      <div className="flex-1">{children}</div>
    </div>
  );
}
