"""Tests for services/plan_limits.py"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.plan_limits import (
    PlanLimits,
    all_plans,
    check_project_limit,
    check_source_limit,
    check_voice_access,
    get_limits,
)


# ─── get_limits ───────────────────────────────────────────────────────────────


def test_get_limits_free():
    limits = get_limits("free")
    assert limits.plan == "free"
    assert limits.project_limit == 3
    assert limits.sources_per_project == 10
    assert limits.voice_calibration is False
    assert limits.price_monthly_usd == 0


def test_get_limits_professional():
    limits = get_limits("professional")
    assert limits.plan == "professional"
    assert limits.project_limit is None
    assert limits.sources_per_project == 50
    assert limits.voice_calibration is True
    assert limits.price_monthly_usd == 49


def test_get_limits_team():
    limits = get_limits("team")
    assert limits.plan == "team"
    assert limits.project_limit is None
    assert limits.sources_per_project == 100
    assert limits.voice_calibration is True
    assert limits.price_monthly_usd == 149


def test_get_limits_enterprise():
    limits = get_limits("enterprise")
    assert limits.plan == "enterprise"
    assert limits.project_limit is None
    assert limits.sources_per_project is None
    assert limits.voice_calibration is True
    assert limits.price_monthly_usd is None


def test_get_limits_unknown_falls_back_to_free():
    limits = get_limits("unknown_plan")
    assert limits.plan == "free"


# ─── all_plans ────────────────────────────────────────────────────────────────


def test_all_plans_returns_four_tiers():
    plans = all_plans()
    plan_names = [p.plan for p in plans]
    assert "free" in plan_names
    assert "professional" in plan_names
    assert "team" in plan_names
    assert "enterprise" in plan_names


def test_all_plans_are_plan_limits_instances():
    for p in all_plans():
        assert isinstance(p, PlanLimits)


# ─── check_project_limit ──────────────────────────────────────────────────────


def test_check_project_limit_free_under_limit():
    # free = 3 projects, count=2 → ok
    check_project_limit("free", 2)  # no exception


def test_check_project_limit_free_at_limit_raises():
    with pytest.raises(HTTPException) as exc_info:
        check_project_limit("free", 3)
    err = exc_info.value
    assert err.status_code == 402
    assert err.detail["code"] == "project_limit_reached"
    assert err.detail["limit"] == 3
    assert err.detail["plan"] == "free"


def test_check_project_limit_free_over_limit_raises():
    with pytest.raises(HTTPException):
        check_project_limit("free", 100)


def test_check_project_limit_professional_unlimited():
    # professional has no project limit
    check_project_limit("professional", 999)  # no exception


def test_check_project_limit_team_unlimited():
    check_project_limit("team", 999)  # no exception


def test_check_project_limit_enterprise_unlimited():
    check_project_limit("enterprise", 999)  # no exception


# ─── check_source_limit ───────────────────────────────────────────────────────


def test_check_source_limit_free_under_limit():
    check_source_limit("free", 9)  # no exception


def test_check_source_limit_free_at_limit_raises():
    with pytest.raises(HTTPException) as exc_info:
        check_source_limit("free", 10)
    err = exc_info.value
    assert err.status_code == 402
    assert err.detail["code"] == "source_limit_reached"
    assert err.detail["limit"] == 10
    assert err.detail["plan"] == "free"


def test_check_source_limit_professional_at_limit_raises():
    with pytest.raises(HTTPException) as exc_info:
        check_source_limit("professional", 50)
    err = exc_info.value
    assert err.status_code == 402
    assert err.detail["limit"] == 50


def test_check_source_limit_professional_under_limit():
    check_source_limit("professional", 49)  # no exception


def test_check_source_limit_team_at_limit_raises():
    with pytest.raises(HTTPException) as exc_info:
        check_source_limit("team", 100)
    assert exc_info.value.status_code == 402


def test_check_source_limit_enterprise_unlimited():
    check_source_limit("enterprise", 10000)  # no exception


# ─── check_voice_access ───────────────────────────────────────────────────────


def test_check_voice_access_free_raises():
    with pytest.raises(HTTPException) as exc_info:
        check_voice_access("free")
    err = exc_info.value
    assert err.status_code == 402
    assert err.detail["code"] == "voice_not_included"
    assert err.detail["plan"] == "free"


def test_check_voice_access_professional_ok():
    check_voice_access("professional")  # no exception


def test_check_voice_access_team_ok():
    check_voice_access("team")  # no exception


def test_check_voice_access_enterprise_ok():
    check_voice_access("enterprise")  # no exception
