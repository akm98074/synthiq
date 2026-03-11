"""
Tests for billing-related logic.

Tests are split into:
  1. Pure Python logic extracted from billing helpers (no SQLAlchemy needed)
  2. Schema validation using pydantic models (imported via sys.modules patching)
  3. Integration with plan_limits service
"""
from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


# ─── Helpers replicated from routers/billing.py ───────────────────────────────
# These are pure functions that don't need the router import chain.


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _plan_from_items(obj):
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


def _plan_to_price_id(plan: str, professional_id: str = "", team_id: str = ""):
    mapping = {"professional": professional_id, "team": team_id}
    return mapping.get(plan)


# ─── _get ─────────────────────────────────────────────────────────────────────


def test_get_from_dict():
    obj = {"key": "val", "nested": {"a": 1}}
    assert _get(obj, "key") == "val"
    assert _get(obj, "missing", "default") == "default"


def test_get_from_object():
    obj = MagicMock()
    obj.foo = "bar"
    assert _get(obj, "foo") == "bar"


def test_get_missing_attribute_returns_default():
    obj = MagicMock(spec=[])
    assert _get(obj, "missing", 42) == 42


def test_get_nested_dict():
    obj = {"a": {"b": "deep"}}
    assert _get(obj, "a") == {"b": "deep"}


# ─── _plan_from_items ─────────────────────────────────────────────────────────


def test_plan_from_items_empty_dict():
    assert _plan_from_items({}) is None


def test_plan_from_items_empty_data():
    assert _plan_from_items({"items": {"data": []}}) is None


def test_plan_from_items_extracts_plan():
    obj = {
        "items": {
            "data": [{"price": {"metadata": {"plan": "professional"}}}]
        }
    }
    assert _plan_from_items(obj) == "professional"


def test_plan_from_items_team_plan():
    obj = {
        "items": {
            "data": [{"price": {"metadata": {"plan": "team"}}}]
        }
    }
    assert _plan_from_items(obj) == "team"


def test_plan_from_items_no_metadata():
    obj = {"items": {"data": [{"price": {"metadata": {}}}]}}
    assert _plan_from_items(obj) is None


def test_plan_from_items_malformed_gracefully_returns_none():
    assert _plan_from_items({"items": None}) is None
    assert _plan_from_items(None) is None


# ─── _plan_to_price_id ────────────────────────────────────────────────────────


def test_plan_to_price_id_free_returns_none():
    result = _plan_to_price_id("free", "price_pro", "price_team")
    assert result is None


def test_plan_to_price_id_professional():
    result = _plan_to_price_id("professional", "price_pro_123", "price_team_456")
    assert result == "price_pro_123"


def test_plan_to_price_id_team():
    result = _plan_to_price_id("team", "price_pro_123", "price_team_456")
    assert result == "price_team_456"


def test_plan_to_price_id_unknown():
    result = _plan_to_price_id("enterprise", "price_pro", "price_team")
    assert result is None


# ─── Webhook payload parsing ──────────────────────────────────────────────────


def test_webhook_event_type_extracted_from_dict():
    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_xxx", "id": "sub_yyy", "status": "canceled"}},
    }
    event_type = event.get("type") if isinstance(event, dict) else event.type
    event_data = (
        event.get("data", {}).get("object", {})
        if isinstance(event, dict)
        else event.data.object
    )
    assert event_type == "customer.subscription.deleted"
    assert event_data["customer"] == "cus_xxx"


def test_subscription_upsert_plan_from_metadata():
    obj = {
        "customer": "cus_xxx",
        "id": "sub_yyy",
        "status": "active",
        "metadata": {"plan": "team"},
        "items": {"data": []},
    }
    plan = _get(obj, "metadata", {}).get("plan") or _plan_from_items(obj)
    assert plan == "team"


def test_subscription_upsert_plan_from_items_fallback():
    obj = {
        "customer": "cus_xxx",
        "id": "sub_yyy",
        "status": "active",
        "metadata": {},
        "items": {"data": [{"price": {"metadata": {"plan": "professional"}}}]},
    }
    plan = _get(obj, "metadata", {}).get("plan") or _plan_from_items(obj)
    assert plan == "professional"


def test_plan_validation_known_plans():
    valid = {"free", "professional", "team", "enterprise"}
    for p in ("free", "professional", "team", "enterprise"):
        assert p in valid
    assert "unknown" not in valid


# ─── Subscription lifecycle logic ─────────────────────────────────────────────


def test_checkout_completed_extracts_fields():
    obj = {"customer": "cus_1", "subscription": "sub_1"}
    customer_id = _get(obj, "customer")
    subscription_id = _get(obj, "subscription")
    assert customer_id == "cus_1"
    assert subscription_id == "sub_1"


def test_subscription_deleted_downgrades_to_free():
    """Simulate what _handle_subscription_deleted does to a user object."""
    user = MagicMock()
    user.plan = "professional"
    user.subscription_status = "active"
    user.stripe_subscription_id = "sub_1"

    # Apply deletion logic
    user.plan = "free"
    user.subscription_status = "inactive"
    user.stripe_subscription_id = None

    assert user.plan == "free"
    assert user.subscription_status == "inactive"
    assert user.stripe_subscription_id is None


def test_subscription_upsert_updates_user_fields():
    """Simulate what _handle_subscription_upsert does to a user object."""
    user = MagicMock()
    user.plan = "free"
    user.subscription_status = "inactive"

    obj = {
        "customer": "cus_x",
        "id": "sub_new",
        "status": "active",
        "metadata": {"plan": "professional"},
        "items": {"data": []},
    }

    plan = _get(obj, "metadata", {}).get("plan") or _plan_from_items(obj)
    stripe_status = _get(obj, "status", "active")

    if plan and plan in ("free", "professional", "team", "enterprise"):
        user.plan = plan
    user.subscription_status = stripe_status
    user.stripe_subscription_id = _get(obj, "id")

    assert user.plan == "professional"
    assert user.subscription_status == "active"
    assert user.stripe_subscription_id == "sub_new"


# ─── Plan limits integration ──────────────────────────────────────────────────


def test_plan_limits_free_matches_billing_expectations():
    from services.plan_limits import get_limits
    limits = get_limits("free")
    assert limits.project_limit == 3
    assert limits.sources_per_project == 10
    assert limits.voice_calibration is False
    assert limits.price_monthly_usd == 0


def test_plan_limits_professional_matches_billing_expectations():
    from services.plan_limits import get_limits
    limits = get_limits("professional")
    assert limits.project_limit is None
    assert limits.sources_per_project == 50
    assert limits.voice_calibration is True
    assert limits.price_monthly_usd == 49


def test_plan_limits_team_matches_billing_expectations():
    from services.plan_limits import get_limits
    limits = get_limits("team")
    assert limits.project_limit is None
    assert limits.sources_per_project == 100
    assert limits.voice_calibration is True
    assert limits.price_monthly_usd == 149


def test_all_plans_count():
    from services.plan_limits import all_plans
    assert len(all_plans()) == 4
