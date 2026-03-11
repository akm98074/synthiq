"use client";

import { useState } from "react";
import { CreditCard, ExternalLink } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useBillingStatus, usePlans, useCheckout, usePortal } from "@/lib/hooks/use-billing";

const STATUS_LABELS: Record<string, { label: string; variant: "default" | "secondary" | "destructive" }> = {
  active: { label: "Active", variant: "default" },
  trialing: { label: "Trial", variant: "secondary" },
  inactive: { label: "Free", variant: "secondary" },
  past_due: { label: "Past due", variant: "destructive" },
  canceled: { label: "Canceled", variant: "destructive" },
};

export function BillingSection() {
  const { data: status, isLoading: statusLoading } = useBillingStatus();
  const { data: plans = [] } = usePlans();
  const checkout = useCheckout();
  const portal = usePortal();

  if (statusLoading) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="h-24 bg-slate-100 rounded-lg animate-pulse" />
        </CardContent>
      </Card>
    );
  }

  const currentPlan = plans.find((p) => p.plan === status?.plan);
  const statusInfo = STATUS_LABELS[status?.subscription_status ?? "inactive"] ?? STATUS_LABELS.inactive;
  const isFreePlan = !status?.plan || status.plan === "free";
  const hasStripeCustomer = Boolean(status?.stripe_customer_id);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold flex items-center gap-2">
          <CreditCard className="w-4 h-4 text-indigo-600" />
          Billing &amp; Plan
        </CardTitle>
        <CardDescription className="text-xs">
          Manage your subscription and billing details.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Current plan display */}
        <div className="flex items-center justify-between rounded-lg border px-4 py-3">
          <div>
            <p className="text-sm font-medium text-slate-900">
              {currentPlan?.label ?? "Free"} Plan
            </p>
            <p className="text-xs text-slate-500 mt-0.5">
              {currentPlan
                ? `${currentPlan.project_limit ?? "Unlimited"} projects · ${currentPlan.sources_per_project ?? "Unlimited"} sources/project`
                : "3 projects · 10 sources/project"}
            </p>
          </div>
          <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
        </div>

        {/* Upgrade CTAs for free users */}
        {isFreePlan && (
          <div className="space-y-2">
            {plans
              .filter((p) => p.plan === "professional" || p.plan === "team")
              .map((plan) => (
                <Button
                  key={plan.plan}
                  variant="outline"
                  size="sm"
                  className="w-full justify-between"
                  disabled={checkout.isPending}
                  onClick={() =>
                    checkout.mutate({
                      plan: plan.plan as "professional" | "team",
                      successUrl: `${window.location.origin}/settings?upgraded=1`,
                      cancelUrl: window.location.href,
                    })
                  }
                >
                  <span>
                    Upgrade to {plan.label}{" "}
                    <span className="text-slate-500 font-normal">
                      — ${plan.price_monthly_usd}/mo
                    </span>
                  </span>
                  <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
                </Button>
              ))}
          </div>
        )}

        {/* Manage subscription for paid users */}
        {!isFreePlan && hasStripeCustomer && (
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            disabled={portal.isPending}
            onClick={() => portal.mutate()}
          >
            <ExternalLink className="w-3.5 h-3.5 mr-2" />
            {portal.isPending ? "Opening portal…" : "Manage subscription"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
