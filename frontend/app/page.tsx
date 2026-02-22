import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function LandingPage() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-b from-slate-50 to-white px-4">
      <div className="max-w-3xl text-center space-y-8">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2">
          <div className="w-10 h-10 rounded-xl bg-indigo-600 flex items-center justify-center">
            <span className="text-white font-bold text-lg">S</span>
          </div>
          <span className="text-2xl font-bold text-slate-900">Synthiq</span>
        </div>

        {/* Headline */}
        <h1 className="text-5xl font-bold text-slate-900 leading-tight">
          From 50 sources to a finished deliverable —{" "}
          <span className="text-indigo-600">in minutes.</span>
        </h1>

        <p className="text-xl text-slate-600 max-w-2xl mx-auto">
          Synthiq ingests any combination of PDFs, URLs, and documents, then
          produces a finished, voice-matched deliverable that reflects your
          synthesis of all sources — not just a summary of each individually.
        </p>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-8 py-4">
          <div>
            <div className="text-3xl font-bold text-indigo-600">3–6 hrs</div>
            <div className="text-sm text-slate-500">Saved per project</div>
          </div>
          <div>
            <div className="text-3xl font-bold text-indigo-600">50</div>
            <div className="text-sm text-slate-500">Sources per project</div>
          </div>
          <div>
            <div className="text-3xl font-bold text-indigo-600">$12B+</div>
            <div className="text-sm text-slate-500">Market opportunity</div>
          </div>
        </div>

        {/* CTA */}
        <div className="flex gap-4 justify-center">
          <Button
            asChild
            size="lg"
            className="bg-indigo-600 hover:bg-indigo-700 text-white"
          >
            <Link href="/sign-up">Get started free</Link>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/sign-in">Sign in</Link>
          </Button>
        </div>

        <p className="text-sm text-slate-400">
          Free plan includes 3 projects · No credit card required
        </p>
      </div>
    </main>
  );
}
