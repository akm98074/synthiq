"use client";

import { Check, Zap } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { usePlans, useCheckout } from "@/lib/hooks/use-billing";

type LimitCode =
  | "project_limit_reached"
  | "source_limit_reached"
  | "voice_not_included";

interface UpgradeModalProps {
  open: boolean;
  onClose: () => void;
  limitCode?: LimitCode;
  message?: string;
}

const LIMIT_COPY: Record<LimitCode, { title: string; description: string }> = {
  project_limit_reached: {
    title: "Project limit reached",
    description:
      "You've used all projects on the Free plan. Upgrade to create unlimited projects.",
  },
  source_limit_reached: {
    title: "Source limit reached",
    description:
      "You've reached the maximum number of sources for this project. Upgrade to add more.",
  },
  voice_not_included: {
    title: "Voice calibration is a paid feature",
    description:
      "Upload your writing samples and let Synthiq match your voice. Available on Professional and Team plans.",
  },
};

const PLAN_FEATURES: Record<string, string[]> = {
  professional: [
    "Unlimited projects",
    "50 sources per project",
    "Voice calibration",
    "PDF & DOCX export",
    "Source map",
  ],
  team: [
    "Unlimited projects",
    "100 sources per project",
    "Voice calibration",
    "PDF & DOCX export",
    "Source map",
    "Priority support",
  ],
};

export function UpgradeModal({
  open,
  onClose,
  limitCode,
  message,
}: UpgradeModalProps) {
  const { data: plans = [] } = usePlans();
  const checkout = useCheckout();

  const copy = limitCode
    ? LIMIT_COPY[limitCode]
    : { title: "Upgrade your plan", description: message ?? "" };

  const paidPlans = plans.filter(
    (p) => p.plan === "professional" || p.plan === "team"
  );

  function handleUpgrade(plan: "professional" | "team") {
    checkout.mutate({
      plan,
      successUrl: `${window.location.origin}/settings?upgraded=1`,
      cancelUrl: window.location.href,
    });
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center">
              <Zap className="w-4 h-4 text-indigo-600" />
            </div>
            <DialogTitle>{copy.title}</DialogTitle>
          </div>
          <DialogDescription className="text-sm text-slate-500">
            {copy.description}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 mt-2">
          {paidPlans.map((plan) => (
            <div
              key={plan.plan}
              className="border rounded-xl p-4 flex flex-col gap-3"
            >
              <div className="flex items-baseline justify-between">
                <div>
                  <span className="font-semibold text-slate-900">
                    {plan.label}
                  </span>
                  {plan.plan === "professional" && (
                    <span className="ml-2 text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
                      Popular
                    </span>
                  )}
                </div>
                <div className="text-right">
                  <span className="text-2xl font-bold text-slate-900">
                    ${plan.price_monthly_usd}
                  </span>
                  <span className="text-slate-500 text-sm">/mo</span>
                </div>
              </div>

              <ul className="space-y-1.5">
                {(PLAN_FEATURES[plan.plan] ?? []).map((feat) => (
                  <li key={feat} className="flex items-center gap-2 text-sm text-slate-600">
                    <Check className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
                    {feat}
                  </li>
                ))}
              </ul>

              <Button
                onClick={() => handleUpgrade(plan.plan as "professional" | "team")}
                disabled={checkout.isPending}
                className="w-full bg-indigo-600 hover:bg-indigo-700 text-white"
              >
                {checkout.isPending ? "Redirecting…" : `Upgrade to ${plan.label}`}
              </Button>
            </div>
          ))}
        </div>

        <p className="text-center text-xs text-slate-400 mt-2">
          Secure payment via Stripe. Cancel anytime.
        </p>
      </DialogContent>
    </Dialog>
  );
}
