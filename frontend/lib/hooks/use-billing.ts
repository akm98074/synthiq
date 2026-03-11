"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { billingApi, PlanInfo, BillingStatus } from "@/lib/api-client";

export function usePlans() {
  return useQuery<PlanInfo[]>({
    queryKey: ["billing-plans"],
    queryFn: () => billingApi.plans(),
    staleTime: 5 * 60_000, // plans rarely change
  });
}

export function useBillingStatus() {
  return useQuery<BillingStatus>({
    queryKey: ["billing-status"],
    queryFn: () => billingApi.status(),
    staleTime: 30_000,
  });
}

export function useCheckout() {
  return useMutation({
    mutationFn: ({
      plan,
      successUrl,
      cancelUrl,
    }: {
      plan: "professional" | "team";
      successUrl?: string;
      cancelUrl?: string;
    }) =>
      billingApi.checkout({
        plan,
        success_url: successUrl ?? window.location.href,
        cancel_url: cancelUrl ?? window.location.href,
      }),
    onSuccess: (data) => {
      window.location.href = data.checkout_url;
    },
  });
}

export function usePortal() {
  return useMutation({
    mutationFn: () => billingApi.portal(),
    onSuccess: (data) => {
      window.location.href = data.portal_url;
    },
  });
}
