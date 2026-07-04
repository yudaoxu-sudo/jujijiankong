from __future__ import annotations

from typing import Any


MECHANISM_FINGERPRINTS = {
    "cross_token_reuse",
    "paired_custody_structure",
    "shared_binance_wallet_router",
}

AUXILIARY_SIGNALS = {
    "bidirectional_high_frequency_net_flat",
    "contract_direct_pool_non_terminal",
}

EXCHANGE_AGGREGATOR_CLASSES = {
    "exchange_aggregator",
    "exchange_aggregator_suspect",
    "exchange_rebalance",
}

PROJECT_REBALANCE_CLASSES = {
    "project_rebalance",
    "project_treasury",
    "mm_or_project_suspect",
    "lp_locker_or_staking",
}


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _intish(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def score_exchange_aggregator_candidate(
    features: dict[str, Any],
    *,
    cross_token_threshold: int = 5,
) -> dict[str, Any]:
    """Score a suspected Binance Alpha custody / aggregator address.

    The classifier requires at least one mechanism fingerprint before it can
    call an address an exchange aggregator suspect. Auxiliary behavior alone
    is routed to MM/project review to avoid washing real project flow.
    """

    shared_tokens = max(
        _intish(features.get("shared_across_tokens")),
        _intish(features.get("cross_token_count")),
        _intish(features.get("distinct_alpha_tokens")),
    )
    signals: set[str] = set()
    score = 0

    if shared_tokens >= cross_token_threshold:
        signals.add("cross_token_reuse")
        score += 3
    if _boolish(features.get("paired_custody_structure")) or _boolish(features.get("stable_token_custody_pair")):
        signals.add("paired_custody_structure")
        score += 3
    if _boolish(features.get("shared_binance_wallet_router")) or _boolish(features.get("uses_shared_router")):
        signals.add("shared_binance_wallet_router")
        score += 3
    if _boolish(features.get("bidirectional_high_frequency_net_flat")) or _boolish(features.get("bidirectional_net_flat")):
        signals.add("bidirectional_high_frequency_net_flat")
        score += 1
    if _boolish(features.get("contract_direct_pool_non_terminal")) or _boolish(features.get("is_contract_direct_pool_non_terminal")):
        signals.add("contract_direct_pool_non_terminal")
        score += 1

    has_mechanism = bool(signals & MECHANISM_FINGERPRINTS)
    if score >= 6 and has_mechanism:
        classification = "exchange_aggregator_suspect"
        action = "manual_confirm_then_allowlist"
        exclude_from_cohort = True
    elif signals & AUXILIARY_SIGNALS and not has_mechanism:
        classification = "mm_or_project_suspect"
        action = "trace_funding_and_next_hop"
        exclude_from_cohort = False
    else:
        classification = "unknown"
        action = "insufficient_evidence"
        exclude_from_cohort = False

    return {
        "classification": classification,
        "score": score,
        "signals": sorted(signals),
        "has_mechanism_fingerprint": has_mechanism,
        "shared_across_tokens": shared_tokens,
        "exclude_from_cohort": exclude_from_cohort,
        "action": action,
    }


def classify_market_flow_effect(label_class: str, *, confirmed_dex_sell: bool = False) -> dict[str, str]:
    label = (label_class or "").strip()
    if confirmed_dex_sell:
        cohort_effect = "exclude_infra_from_cohort" if label in EXCHANGE_AGGREGATOR_CLASSES else "confirmed_sell"
        return {
            "market_effect": "bearish_confirmed_dex_sell",
            "cohort_effect": cohort_effect,
            "action": "keep_bearish_signal",
        }
    if label in EXCHANGE_AGGREGATOR_CLASSES:
        return {
            "market_effect": "exchange_rebalance_reference",
            "cohort_effect": "exclude_from_cohort",
            "action": "use_long_window_net_exposure_only",
        }
    if label in PROJECT_REBALANCE_CLASSES:
        return {
            "market_effect": "transfer_only_neutral_watch",
            "cohort_effect": "exclude_as_smart_money",
            "action": "trace_next_hop_before_sell_claim",
        }
    if label in {"cex_deposit", "cex_hot_wallet"}:
        return {
            "market_effect": "pending_sell_or_mm_inventory",
            "cohort_effect": "not_confirmed_sell",
            "action": "watch_cex_follow_through",
        }
    return {
        "market_effect": "unknown",
        "cohort_effect": "trace_next_hop",
        "action": "do_not_claim_sell_without_swap",
    }
