"""
Billing endpoints — Stripe Checkout, Customer Portal, and webhook handler.

Endpoints:
  GET  /billing/plans           — list plan metadata (pricing, limits)
  GET  /billing/status          — current user's plan & subscription status
  POST /billing/checkout        — create Stripe Checkout session URL
  POST /billing/portal          — create Stripe Customer Portal session URL
  POST /billing/webhook         — Stripe webhook (raw body, signature verified)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import settings
from database import get_db
from models.database import User
from models.schemas import (
    BillingCheckoutRequest,
    BillingCheckoutResponse,
    BillingPortalResponse,
    BillingStatusOut,
    PlanInfoOut,
)
from services.plan_limits import all_plans

log = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

# ─── Plan catalogue ────────────────────────────────────────────────────────────


@router.get("/plans", response_model=list[PlanInfoOut])
async def list_plans():
    """Return plan metadata for all tiers."""
    return [
        PlanInfoOut(
            plan=p.plan,
            label=p.label,
            price_monthly_usd=p.price_monthly_usd,
            project_limit=p.project_limit,
            sources_per_project=p.sources_per_project,
            voice_calibration=p.voice_calibration,
        )
        for p in all_plans()
    ]


# ─── Current billing status ────────────────────────────────────────────────────


@router.get("/status", response_model=BillingStatusOut)
async def billing_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return BillingStatusOut(
        plan=current_user.plan,
        subscription_status=current_user.subscription_status,
        stripe_customer_id=current_user.stripe_customer_id,
    )


# ─── Stripe Checkout ───────────────────────────────────────────────────────────


@router.post("/checkout", response_model=BillingCheckoutResponse)
async def create_checkout(
    payload: BillingCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a Stripe Checkout session for plan upgrade.

    Returns a URL the frontend should redirect to.
    Falls back to a dev-mode placeholder if Stripe is not configured.
    """
    if not settings.stripe_secret_key:
        # Dev mode: return a placeholder URL
        return BillingCheckoutResponse(
            checkout_url=f"{settings.api_url}/billing/dev-checkout?plan={payload.plan}"
        )

    import stripe  # noqa: PLC0415

    stripe.api_key = settings.stripe_secret_key

    # Map plan → Stripe Price ID from config (set in env)
    price_id = _plan_to_price_id(payload.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {payload.plan}")

    # Get or create Stripe customer
    customer_id = current_user.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=current_user.email,
            metadata={"synthiq_user_id": current_user.id},
        )
        customer_id = customer.id
        current_user.stripe_customer_id = customer_id
        await db.commit()

    success_url = f"{payload.success_url}?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = payload.cancel_url

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        subscription_data={
            "metadata": {"synthiq_user_id": current_user.id, "plan": payload.plan}
        },
    )
    return BillingCheckoutResponse(checkout_url=session.url)


# ─── Stripe Customer Portal ────────────────────────────────────────────────────


@router.post("/portal", response_model=BillingPortalResponse)
async def create_portal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a Stripe Customer Portal session (manage subscription, invoices).
    """
    if not settings.stripe_secret_key:
        return BillingPortalResponse(
            portal_url=f"{settings.api_url}/billing/dev-portal"
        )

    import stripe  # noqa: PLC0415

    stripe.api_key = settings.stripe_secret_key

    if not current_user.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer found — subscribe first.",
        )

    return_url = request.headers.get("referer", f"{settings.api_url}/settings")
    portal = stripe.billing_portal.Session.create(
        customer=current_user.stripe_customer_id,
        return_url=return_url,
    )
    return BillingPortalResponse(portal_url=portal.url)


# ─── Stripe Webhook ────────────────────────────────────────────────────────────


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive and process Stripe webhook events.

    Handled events:
      customer.subscription.created / updated / deleted
      checkout.session.completed
    """
    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if settings.stripe_secret_key and settings.stripe_webhook_secret:
        import stripe  # noqa: PLC0415

        stripe.api_key = settings.stripe_secret_key
        try:
            event = stripe.Webhook.construct_event(
                raw_body, sig_header, settings.stripe_webhook_secret
            )
        except stripe.error.SignatureVerificationError:
            log.warning("Stripe webhook signature verification failed")
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # Dev/test mode: parse JSON directly without verification
        try:
            event = json.loads(raw_body)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type") if isinstance(event, dict) else event.type
    event_data = (
        event.get("data", {}).get("object", {})
        if isinstance(event, dict)
        else event.data.object
    )

    log.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(db, event_data)

    elif event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        await _handle_subscription_upsert(db, event_data)

    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(db, event_data)

    return {"received": True}


# ─── Webhook helpers ──────────────────────────────────────────────────────────


async def _handle_checkout_completed(
    db: AsyncSession, obj: dict[str, Any]
) -> None:
    customer_id = _get(obj, "customer")
    subscription_id = _get(obj, "subscription")
    if not customer_id:
        return

    user = await _user_by_customer(db, customer_id)
    if user is None:
        log.warning("No user for Stripe customer %s", customer_id)
        return

    if subscription_id:
        user.stripe_subscription_id = subscription_id

    user.subscription_status = "active"
    await db.commit()


async def _handle_subscription_upsert(
    db: AsyncSession, obj: dict[str, Any]
) -> None:
    customer_id = _get(obj, "customer")
    subscription_id = _get(obj, "id")
    stripe_status = _get(obj, "status", "active")  # active | trialing | past_due …

    # Derive plan from subscription metadata or items
    plan = _get(obj, "metadata", {}).get("plan") or _plan_from_items(obj)

    user = await _user_by_customer(db, customer_id)
    if user is None:
        return

    user.stripe_subscription_id = subscription_id
    user.subscription_status = stripe_status
    if plan and plan in ("free", "professional", "team", "enterprise"):
        user.plan = plan

    await db.commit()
    log.info("Subscription updated — user %s → plan=%s status=%s", user.id, plan, stripe_status)


async def _handle_subscription_deleted(
    db: AsyncSession, obj: dict[str, Any]
) -> None:
    customer_id = _get(obj, "customer")
    user = await _user_by_customer(db, customer_id)
    if user is None:
        return

    user.plan = "free"
    user.subscription_status = "inactive"
    user.stripe_subscription_id = None
    await db.commit()
    log.info("Subscription cancelled — user %s reverted to free", user.id)


async def _user_by_customer(
    db: AsyncSession, customer_id: str
) -> User | None:
    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    return result.scalar_one_or_none()


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Safely get from dict or Stripe object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _plan_from_items(obj: Any) -> str | None:
    """Extract plan name from subscription items metadata."""
    try:
        items = _get(obj, "items", {})
        data = items.get("data", []) if isinstance(items, dict) else []
        if data:
            price = _get(data[0], "price", {})
            meta = _get(price, "metadata", {}) if isinstance(price, dict) else {}
            return meta.get("plan")
    except Exception:
        pass
    return None


def _plan_to_price_id(plan: str) -> str | None:
    """Map plan name to Stripe Price ID from environment variables."""
    mapping = {
        "professional": settings.stripe_price_professional,
        "team": settings.stripe_price_team,
    }
    return mapping.get(plan)
