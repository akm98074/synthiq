"""
Central plan limits — single source of truth for all enforcement checks.

Plan tiers:
  free          3 projects  |  10 sources/project  |  no voice
  professional  unlimited   |  50 sources/project  |  voice included
  team          unlimited   | 100 sources/project  |  voice included
  enterprise    unlimited   | unlimited            |  voice included

Usage: import and call check_* helpers from routers.  Each raises
HTTPException(402) with a machine-readable `code` field so the frontend
can render the correct upgrade modal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, status

Plan = Literal["free", "professional", "team", "enterprise"]


@dataclass(frozen=True)
class PlanLimits:
    plan: str
    project_limit: int | None        # None = unlimited
    sources_per_project: int | None  # None = unlimited
    voice_calibration: bool
    price_monthly_usd: int | None    # None = contact sales
    label: str


_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        plan="free",
        project_limit=3,
        sources_per_project=10,
        voice_calibration=False,
        price_monthly_usd=0,
        label="Free",
    ),
    "professional": PlanLimits(
        plan="professional",
        project_limit=None,
        sources_per_project=50,
        voice_calibration=True,
        price_monthly_usd=49,
        label="Professional",
    ),
    "team": PlanLimits(
        plan="team",
        project_limit=None,
        sources_per_project=100,
        voice_calibration=True,
        price_monthly_usd=149,
        label="Team",
    ),
    "enterprise": PlanLimits(
        plan="enterprise",
        project_limit=None,
        sources_per_project=None,
        voice_calibration=True,
        price_monthly_usd=None,
        label="Enterprise",
    ),
}


def get_limits(plan: str) -> PlanLimits:
    return _LIMITS.get(plan, _LIMITS["free"])


def all_plans() -> list[PlanLimits]:
    return list(_LIMITS.values())


# ─── Enforcement helpers ───────────────────────────────────────────────────────


def check_project_limit(plan: str, current_count: int) -> None:
    """Raise 402 if the user has hit their project quota."""
    limits = get_limits(plan)
    if limits.project_limit is not None and current_count >= limits.project_limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "project_limit_reached",
                "limit": limits.project_limit,
                "plan": plan,
                "message": (
                    f"Free plan allows {limits.project_limit} projects. "
                    "Upgrade to Professional to create unlimited projects."
                ),
            },
        )


def check_source_limit(plan: str, current_count: int) -> None:
    """Raise 402 if the project has hit its source quota."""
    limits = get_limits(plan)
    if limits.sources_per_project is not None and current_count >= limits.sources_per_project:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "source_limit_reached",
                "limit": limits.sources_per_project,
                "plan": plan,
                "message": (
                    f"{limits.label} plan allows {limits.sources_per_project} sources per project. "
                    "Upgrade to add more."
                ),
            },
        )


def check_voice_access(plan: str) -> None:
    """Raise 402 if the user's plan does not include voice calibration."""
    limits = get_limits(plan)
    if not limits.voice_calibration:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "voice_not_included",
                "plan": plan,
                "message": (
                    "Voice calibration is available on Professional and Team plans. "
                    "Upgrade to unlock this feature."
                ),
            },
        )
