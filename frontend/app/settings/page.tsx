"use client";

import Link from "next/link";
import { UserButton } from "@clerk/nextjs";
import { ArrowLeft, Mic2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { SampleUploader } from "@/components/voice/sample-uploader";
import { StyleSignatureCard } from "@/components/voice/style-signature-card";
import { useVoiceProfile } from "@/lib/hooks/use-voice";
import { BillingSection } from "@/components/billing/billing-section";

export default function SettingsPage() {
  const { data: profile, isLoading } = useVoiceProfile();

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Nav */}
      <header className="bg-white border-b px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            href="/dashboard"
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Dashboard
          </Link>
          <span className="text-slate-300">|</span>
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-indigo-600 flex items-center justify-center">
              <span className="text-white font-bold text-xs">S</span>
            </div>
            <span className="font-semibold text-slate-900 text-sm">Synthiq</span>
          </div>
        </div>
        <UserButton afterSignOutUrl="/" />
      </header>

      <main className="max-w-2xl mx-auto px-6 py-10 space-y-10">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Settings</h1>
          <p className="text-slate-500 text-sm mt-1">
            Manage your account preferences, plan, and voice calibration.
          </p>
        </div>

        {/* Billing section */}
        <section className="space-y-4">
          <h2 className="text-lg font-semibold text-slate-900">Billing</h2>
          <BillingSection />
        </section>

        {/* Voice Calibration section */}
        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <Mic2 className="w-5 h-5 text-indigo-600" />
            <h2 className="text-lg font-semibold text-slate-900">
              Voice Calibration
            </h2>
          </div>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">
                Upload Writing Samples
              </CardTitle>
              <CardDescription className="text-xs">
                Upload 3-5 past documents that reflect your writing style.
                Synthiq will analyse them to calibrate drafts to sound like you.
                Supported formats: PDF, DOCX, TXT.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="h-32 rounded-lg bg-slate-100 animate-pulse" />
              ) : (
                <SampleUploader profile={profile ?? null} />
              )}
            </CardContent>
          </Card>

          {/* Style Signature display */}
          {!isLoading && profile?.style_signature && (
            <StyleSignatureCard
              signature={profile.style_signature}
              sampleCount={profile.sample_count}
            />
          )}

          {/* Generated system prompt preview */}
          {!isLoading && profile?.voice_system_prompt && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold">
                  Voice System Prompt
                </CardTitle>
                <CardDescription className="text-xs">
                  This prompt is injected when drafting with voice calibration enabled.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <pre className="text-xs text-slate-600 bg-slate-50 rounded-lg p-3 whitespace-pre-wrap font-mono leading-relaxed">
                  {profile.voice_system_prompt}
                </pre>
              </CardContent>
            </Card>
          )}

          {/* Empty state */}
          {!isLoading && !profile && (
            <p className="text-sm text-slate-400 text-center py-4">
              Upload at least one writing sample to generate your voice profile.
            </p>
          )}
        </section>
      </main>
    </div>
  );
}
