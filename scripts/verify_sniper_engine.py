#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "output" / "sniper_engine" / "verification_report.md"
PYCACHE_DIR = Path(tempfile.gettempdir()) / "sniper_pycache"


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    required_files = [
        ROOT / "sniper_engine" / "scoring.py",
        ROOT / "sniper_engine" / "local_sources.py",
        ROOT / "sniper_engine" / "rpc.py",
        ROOT / "sniper_engine" / "project_registry.py",
        ROOT / "sniper_engine" / "address_labels.py",
        ROOT / "sniper_engine" / "entity_clustering.py",
        ROOT / "sniper_engine" / "exchange_aggregator.py",
        ROOT / "sniper_engine" / "token_aliases.py",
        ROOT / "scripts" / "sniper_score_local.py",
        ROOT / "scripts" / "alpha_project_watch.py",
        ROOT / "scripts" / "alpha_holder_concentration_watch.py",
        ROOT / "scripts" / "alpha_prelaunch_watch.py",
        ROOT / "scripts" / "alpha_opening_block_watch.py",
        ROOT / "scripts" / "alpha_price_momentum_watch.py",
        ROOT / "scripts" / "alpha_intraday_flow_watch.py",
        ROOT / "scripts" / "verify_alpha_aggregator_trace.py",
        ROOT / "scripts" / "collect_alpha_trace_bundle.py",
        ROOT / "scripts" / "review_alpha_swap_samples.py",
        ROOT / "scripts" / "review_alpha_swap_txs.py",
        ROOT / "scripts" / "review_exchange_wallet_labels.py",
        ROOT / "scripts" / "review_cex_sweep_patterns.py",
        ROOT / "scripts" / "review_funding_source_clusters.py",
        ROOT / "scripts" / "review_opening_cohort_funders.py",
        ROOT / "scripts" / "review_pancake_v4_samples.py",
        ROOT / "scripts" / "x_mcp_readiness.py",
        ROOT / "scripts" / "external_aux_source_readiness.py",
        ROOT / "scripts" / "audit_celue_integration.py",
        ROOT / "scripts" / "decode_pancake_v4_execute.py",
        ROOT / "scripts" / "build_pancake_v4_roundtrip_fixture.py",
        ROOT / "scripts" / "verify_pancake_v4_roundtrip_fixture.py",
        ROOT / "scripts" / "probe_pancake_v4_state_override.py",
        ROOT / "scripts" / "simulate_pancake_v4_roundtrip_call.py",
        ROOT / "scripts" / "alpha_opening_sprint.sh",
        ROOT / "scripts" / "arx_launch_watch.py",
        ROOT / "scripts" / "arx_opening_block_watch.py",
        ROOT / "scripts" / "arx_opening_sprint.sh",
        ROOT / "scripts" / "deploy_to_server.sh",
        ROOT / "scripts" / "build_alpha_daily_report.py",
        ROOT / "scripts" / "prediction_market_watch.py",
        ROOT / "scripts" / "perp_oi_funding_watch.py",
        ROOT / "scripts" / "surf_aux_market_watch.py",
        ROOT / "scripts" / "telegram_signal_collector.py",
        ROOT / "scripts" / "telegram_user_signal_collector.py",
        ROOT / "scripts" / "telegram_user_login.py",
        ROOT / "scripts" / "add_telegram_source.py",
        ROOT / "scripts" / "analyze_pancake_pool_tx.py",
        ROOT / "scripts" / "ingest_alpha_signal.py",
        ROOT / "scripts" / "build_monitored_wallets.py",
        ROOT / "scripts" / "o1_address_attribution.py",
        ROOT / "scripts" / "sniper_monitor.py",
        ROOT / "scripts" / "server_run_once.sh",
        ROOT / "scripts" / "o1_block_verifier.py",
        ROOT / "scripts" / "o1_decode_pancake_v3.py",
        ROOT / "scripts" / "o1_trace_front_buyers.py",
        ROOT / "scripts" / "summarize_hertzflow_skeleton.py",
        ROOT / "docs" / "alpha_swap_trace_request_prompt.md",
        ROOT / "docs" / "kol_strategy_intake_prompt.md",
        ROOT / "docs" / "pancake_v4_roundtrip_request_prompt.md",
        ROOT / "docs" / "pancake_v4_roundtrip_implementation_prompt.md",
        ROOT / "docs" / "cex_wallet_evidence_request_prompt.md",
        ROOT / "docs" / "x_mcp_setup.md",
        ROOT / "config" / "watchlist.example.json",
        ROOT / "config" / "external_aux_sources.json",
        ROOT / "config" / "token_aliases.json",
        ROOT / "config" / "current_alpha_watchlist.json",
        ROOT / "config" / "global_address_labels.json",
        ROOT / "config" / "prediction_markets.example.json",
        ROOT / "config" / "current_prediction_markets.json",
        ROOT / "config" / "telegram_user_sources.example.json",
        ROOT / "config" / "telegram_user_sources.json",
        ROOT / "config" / "monitored_wallets.json",
        ROOT / "config" / "pancake_v4_simulation_samples.json",
        ROOT / "input" / "signals" / "README.md",
        ROOT / "output" / "o1_pancake_v3_decode" / "decoded_mint.json",
        ROOT / "output" / "o1_pancake_v3_decode" / "decoded_swaps.csv",
        ROOT / "output" / "o1_front_buyers_trace" / "front_buyers_trace.csv",
        ROOT / "output" / "monitoring" / "latest_snapshot.json",
        ROOT / "output" / "monitoring" / "alerts.md",
        ROOT / "output" / "monitoring" / "telegram_payload.txt",
        ROOT / "output" / "alpha_project_watch" / "latest.json",
        ROOT / "output" / "alpha_project_watch" / "latest.md",
        ROOT / "output" / "arx_launch_watch" / "latest.json",
        ROOT / "output" / "arx_launch_watch" / "latest.md",
        ROOT / "output" / "arx_opening_block_watch" / "latest.json",
        ROOT / "output" / "arx_opening_block_watch" / "latest.md",
        ROOT / "output" / "prediction_markets" / "latest_prediction_markets.json",
        ROOT / "output" / "prediction_markets" / "prediction_markets.md",
        ROOT / "output" / "surf_aux_market_watch" / "latest.json",
        ROOT / "output" / "surf_aux_market_watch" / "latest.md",
        ROOT / "output" / "external_aux_sources" / "latest.json",
        ROOT / "output" / "external_aux_sources" / "latest.md",
        ROOT / "output" / "o1_address_attribution" / "address_attribution.csv",
        ROOT / "output" / "o1_address_attribution" / "o1_address_attribution.md",
        ROOT / "output" / "aliideez_x_research" / "analysis" / "method_index.csv",
        ROOT / "output" / "0xcrypto_max_x_research" / "analysis" / "method_index.csv",
    ]
    for path in required_files:
        checks.append((f"file exists: {path.relative_to(ROOT)}", path.exists(), ""))

    daily_reports = sorted((ROOT / "reports").glob("*_alpha_sniper_daily.md"))
    checks.append(("daily alpha report exists", bool(daily_reports), daily_reports[-1].name if daily_reports else ""))

    config_ok = False
    config_msg = ""
    try:
        json.loads((ROOT / "config" / "watchlist.example.json").read_text(encoding="utf-8"))
        config_ok = True
    except Exception as exc:
        config_msg = str(exc)
    checks.append(("watchlist example JSON parses", config_ok, config_msg))

    external_aux_config_ok = False
    external_aux_config_msg = ""
    try:
        aux_config = json.loads((ROOT / "config" / "external_aux_sources.json").read_text(encoding="utf-8"))
        source_ids = {str(row.get("id", "")) for row in aux_config.get("sources", [])}
        required_sources = {"coinglass", "coinank", "gmgn", "debot_ai", "surf"}
        rules = aux_config.get("rules", {})
        external_aux_config_ok = (
            aux_config.get("schema") == "external_aux_sources.v1"
            and required_sources.issubset(source_ids)
            and rules.get("unvalidated_source_policy") == "can_enrich_context_but_cannot_emit_buy_sell_action"
        )
        external_aux_config_msg = f"{len(source_ids)} sources, ids={','.join(sorted(source_ids))}"
    except Exception as exc:
        external_aux_config_msg = str(exc)
    checks.append(("external auxiliary source config parses", external_aux_config_ok, external_aux_config_msg))

    token_alias_config_ok = False
    token_alias_config_msg = ""
    try:
        alias_config = json.loads((ROOT / "config" / "token_aliases.json").read_text(encoding="utf-8"))
        rows = alias_config.get("tokens", [])
        by_address = {str(row.get("address", "")).lower(): row for row in rows if isinstance(row, dict)}
        wdataip = by_address.get("0xa37eded373c5cdf88644db7c6b89f222e756afb2", {})
        token_alias_config_ok = (
            alias_config.get("schema") == "token_aliases.v1"
            and wdataip.get("raw_symbol") == "WDATAIP"
            and wdataip.get("display_symbol") == "DATA"
            and wdataip.get("project_name") == "Data Network"
        )
        token_alias_config_msg = f"{len(rows)} aliases, wdataip={bool(wdataip)}"
    except Exception as exc:
        token_alias_config_msg = str(exc)
    checks.append(("token alias config parses", token_alias_config_ok, token_alias_config_msg))

    global_labels_ok = False
    global_labels_msg = ""
    try:
        labels = json.loads((ROOT / "config" / "global_address_labels.json").read_text(encoding="utf-8"))
        bsc_labels = labels.get("chains", {}).get("bsc", [])
        classes = {row.get("class") for row in bsc_labels if isinstance(row, dict)}
        global_labels_ok = bool(bsc_labels) and {"dex_router", "dex_quoter", "dex_vault", "permit2", "lp_position_manager", "pool_manager", "cex_hot_wallet", "cex_deposit"}.issubset(classes)
        global_labels_msg = f"{len(bsc_labels)} bsc labels, classes={','.join(sorted(str(item) for item in classes if item))}"
    except Exception as exc:
        global_labels_msg = str(exc)
    checks.append(("global address labels JSON parses", global_labels_ok, global_labels_msg))

    cex_labels_ok = False
    cex_labels_msg = ""
    try:
        bsc_by_address = {str(row.get("address", "")).lower(): row for row in bsc_labels if isinstance(row, dict)}
        high_confidence = {
            "0x8894e0a0c962cb723c1976a4421c95949be2d4e3": "cex_hot_wallet",
            "0xf977814e90da44bfa03b6295a0616a897441acec": "cex_hot_wallet",
            "0x5a52e96bacd1056251811211bc712e1b270efcb1": "cex_hot_wallet",
            "0x28c6c06298d514db089934071355e5743bf21d60": "cex_hot_wallet",
            "0xf89d7b9c864f589bbf53a82105107622b35eaa40": "cex_hot_wallet",
            "0x0d0707963952f2fba59dd06f2b425ace40b492fe": "cex_hot_wallet",
            "0x53f78a071d04224b8e254e243fffc6d9f2f3fa23": "cex_hot_wallet",
            "0xdd3cb5c974601bc3974d908ea4a86020f9999e0c": "cex_hot_wallet",
            "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "cex_deposit",
        }
        missing = [addr for addr, label_class in high_confidence.items() if bsc_by_address.get(addr, {}).get("class") != label_class]
        rejected_mexc_fragment = "0x56ed7392661f496d10e9119d41123fa3f58405acb59ddf8992e250696dd63f75edd0c3"
        cex_labels_ok = not missing and rejected_mexc_fragment not in bsc_by_address
        cex_labels_msg = f"imported={len(high_confidence) - len(missing)}/{len(high_confidence)}, missing={missing}, invalid_mexc_imported={rejected_mexc_fragment in bsc_by_address}"
    except Exception as exc:
        cex_labels_msg = str(exc)
    checks.append(("global CEX labels imported with invalid sample rejected", cex_labels_ok, cex_labels_msg))

    exchange_wallet_review_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='exchange_wallet_review_'))
source = work / 'wallets.json'
out_dir = work / 'out'
rows = [
    {
        'chain': 'bsc',
        'address': '0x1111111111111111111111111111111111111111',
        'exchange': 'TestEx',
        'type': 'hot_wallet',
        'confidence': 'high',
        'evidence': 'BscScan label: TestEx Hot Wallet',
        'source_url': 'https://example.com/1',
    },
    {
        'chain': 'bsc',
        'address': '0x2222',
        'exchange': 'BadEx',
        'type': 'hot_wallet',
        'confidence': 'high',
        'evidence': 'bad address',
    },
    {
        'chain': 'bsc',
        'address': '0x3333333333333333333333333333333333333333',
        'exchange': 'MidEx',
        'type': 'deposit_wallet',
        'confidence': 'medium',
        'evidence': 'not enough evidence',
    },
    {
        'chain': 'bsc',
        'address': '0x4444444444444444444444444444444444444444',
        'exchange': 'RouterEx',
        'type': 'router',
        'confidence': 'high',
        'evidence': 'protocol address',
    },
]
source.write_text(json.dumps(rows), encoding='utf-8')
result = subprocess.run(
    [sys.executable, str(root / 'scripts' / 'review_exchange_wallet_labels.py'), '--input', str(source), '--out-dir', str(out_dir)],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
review = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert review['counts']['accepted_candidate'] == 1, review
assert review['counts']['rejected'] == 3, review
proposal = review['label_proposals'][0]
assert proposal['class'] == 'cex_hot_wallet', proposal
assert proposal['exchange'] == 'TestEx', proposal
"""
    exchange_wallet_review_result = subprocess.run(
        [sys.executable, "-c", exchange_wallet_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "exchange wallet label review smoke test",
            exchange_wallet_review_result.returncode == 0,
            exchange_wallet_review_result.stderr.strip(),
        )
    )

    cex_sweep_review_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='cex_sweep_review_'))
source = work / 'sweeps.json'
out_dir = work / 'out'
binance_hot = '0x8894e0a0c962cb723c1976a4421c95949be2d4e3'
rows = [
    {
        'chain': 'bsc',
        'address': '0x1111111111111111111111111111111111111111',
        'exchange': 'Binance',
        'type': 'deposit_wallet',
        'confidence': 'high',
        'sweep_paths': [
            {'tx_hash': '0x' + 'a' * 64, 'to': binance_hot},
            {'tx_hash': '0x' + 'b' * 64, 'to': binance_hot},
            {'tx_hash': '0x' + 'c' * 64, 'to': binance_hot},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x2222222222222222222222222222222222222222',
        'exchange': 'Binance',
        'type': 'deposit_wallet',
        'confidence': 'high',
        'sweep_paths': [
            {'tx_hash': '0x' + 'd' * 64, 'to': binance_hot},
            {'tx_hash': '0x' + 'e' * 64, 'to': binance_hot},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x3333333333333333333333333333333333333333',
        'exchange': 'Unknown',
        'type': 'sweep_wallet',
        'confidence': 'high',
        'sweep_paths': [
            {'tx_hash': '0x' + '1' * 64, 'to': '0x4444444444444444444444444444444444444444'},
            {'tx_hash': '0x' + '2' * 64, 'to': '0x4444444444444444444444444444444444444444'},
            {'tx_hash': '0x' + '3' * 64, 'to': '0x4444444444444444444444444444444444444444'},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x5555555555555555555555555555555555555555',
        'exchange': 'Binance',
        'type': 'deposit_wallet',
        'confidence': 'high',
        'asset_type': 'native_bnb',
        'sweep_paths': [
            {'tx_hash': '0x' + '4' * 64, 'to': binance_hot, 'asset': 'BNB'},
            {'tx_hash': '0x' + '5' * 64, 'to': binance_hot, 'asset': 'BNB'},
            {'tx_hash': '0x' + '6' * 64, 'to': binance_hot, 'asset': 'BNB'},
        ],
    },
    {
        'chain': 'bsc',
        'address': '0x6666666666666666666666666666666666666666',
        'exchange': 'Binance',
        'type': 'deposit_wallet',
        'confidence': 'high',
        'sweep_paths': [
            {'tx_hash': '0x' + '7' * 64, 'hot_wallet': binance_hot, 'direction': 'in_from_cex_hot_wallet'},
            {'tx_hash': '0x' + '8' * 64, 'hot_wallet': binance_hot, 'direction': 'in_from_cex_hot_wallet'},
            {'tx_hash': '0x' + '9' * 64, 'hot_wallet': binance_hot, 'direction': 'in_from_cex_hot_wallet'},
        ],
    },
]
source.write_text(json.dumps(rows), encoding='utf-8')
result = subprocess.run(
    [sys.executable, str(root / 'scripts' / 'review_cex_sweep_patterns.py'), '--input', str(source), '--out-dir', str(out_dir)],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
review = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert review['counts']['accepted_candidate'] == 1, review
assert review['counts']['needs_manual_review'] == 4, review
assert any(item['reason'] == 'native_asset_only' for item in review['reviewed']), review
assert any(item['reason'] == 'missing_sweep_target' and item['address'] == '0x6666666666666666666666666666666666666666' for item in review['reviewed']), review
proposal = review['label_proposals'][0]
assert proposal['class'] == 'cex_deposit', proposal
assert proposal['exchange'] == 'Binance', proposal
assert proposal['address'] == '0x1111111111111111111111111111111111111111', proposal
"""
    cex_sweep_review_result = subprocess.run(
        [sys.executable, "-c", cex_sweep_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "CEX sweep-pattern review smoke test",
            cex_sweep_review_result.returncode == 0,
            cex_sweep_review_result.stderr.strip(),
        )
    )

    pancake_v4_samples_ok = False
    pancake_v4_samples_msg = ""
    try:
        samples = json.loads((ROOT / "config" / "pancake_v4_simulation_samples.json").read_text(encoding="utf-8"))
        accepted = samples.get("accepted_samples", [])
        rejected = samples.get("rejected_samples", [])
        router = str(samples.get("universal_router") or "").lower()
        success_count = sum(1 for row in accepted if row.get("status") == 1)
        fail_count = sum(1 for row in accepted if row.get("status") == 0)
        selectors = {row.get("selector") for row in accepted}
        all_to_router = all(str(row.get("tx_to") or "").lower() == router for row in accepted)
        by_hash = {str(row.get("tx_hash") or "").lower(): row for row in accepted}
        rejected_hashes = {str(row.get("tx_hash") or "").lower() for row in rejected}
        arx_buy = by_hash.get("0x046673c3b5217b271da8b2be94d892537f9b120865be9bedb49db9959bd582db", {})
        arx_sell = by_hash.get("0xdbcf8b8d95418c0d08b16fde926abaa9d2355e340e5d6d1d503a75430848e4e7", {})
        docx_extra = by_hash.get("0xcc31145b750ca84cd25b4855beaecf0a8a0379c56145a7b7a695a8c29e4dbbf5", {})
        pancake_v4_samples_ok = (
            samples.get("schema") == "pancake_v4_simulation_samples.v1"
            and len(accepted) == 7
            and len(rejected) == 2
            and success_count == 5
            and fail_count == 2
            and all_to_router
            and {"0x3593564c", "0x24856bc3"}.issubset(selectors)
            and arx_buy.get("sample_type") == "successful_universal_router_buy"
            and arx_sell.get("sample_type") == "successful_universal_router_sell"
            and docx_extra.get("selector") == "0x24856bc3"
            and "0xeb126ee663d7af5c9e81a125b816e7b8ef3daf4876b764fad242663f042c13eb" in rejected_hashes
            and "0x1d33f0c687e8a362fb5c1455a534ca6a7614eb883f7869bc995153636316e73b" in rejected_hashes
            and "local sellability gate is now implemented" in str(samples.get("open_gap") or "")
            and "Route samples still do not unlock automatic follow wording" in str(samples.get("open_gap") or "")
        )
        pancake_v4_samples_msg = f"accepted={len(accepted)}, rejected={len(rejected)}, success={success_count}, fail={fail_count}, selectors={sorted(str(item) for item in selectors)}"
    except Exception as exc:
        pancake_v4_samples_msg = str(exc)
    checks.append(("pancake v4 simulation samples reviewed", pancake_v4_samples_ok, pancake_v4_samples_msg))

    pancake_v4_roundtrip_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
out_dir = Path(tempfile.mkdtemp(prefix='pancake_v4_roundtrip_fixture_'))
result = subprocess.run(
    [sys.executable, str(root / 'scripts' / 'build_pancake_v4_roundtrip_fixture.py'), '--out-dir', str(out_dir)],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
fixture = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert fixture['schema'] == 'pancake_v4_roundtrip_fixture.v1', fixture
assert fixture['status'] == 'calldata_fixture_only', fixture
assert fixture['selector'] == '0x3593564c', fixture
assert fixture['commands'] == ['10', '10'], fixture
decoded_commands = fixture['decoded']['commands']
assert len(decoded_commands) == 2, decoded_commands
buy_swap = decoded_commands[0]['decoded_input']['actions'][0]['decoded_param']
sell_swap = decoded_commands[1]['decoded_input']['actions'][0]['decoded_param']
buy_settle = decoded_commands[0]['decoded_input']['actions'][1]['decoded_param']
sell_settle = decoded_commands[1]['decoded_input']['actions'][1]['decoded_param']
buy_take_all = decoded_commands[0]['decoded_input']['actions'][2]['decoded_param']
sell_take_all = decoded_commands[1]['decoded_input']['actions'][2]['decoded_param']
assert buy_swap['zero_for_one'] is True, buy_swap
assert sell_swap['zero_for_one'] is False, sell_swap
assert buy_swap['hook_data_length'] == 0, buy_swap
assert sell_swap['hook_data_length'] == 0, sell_swap
assert buy_settle['payer_is_user'] is True, buy_settle
assert sell_settle['payer_is_user'] is False, sell_settle
assert buy_take_all['recipient'] == '0x0000000000000000000000000000000000000002', buy_take_all
assert sell_take_all['recipient'] == '0x0000000000000000000000000000000000000001', sell_take_all
assert fixture['calldata'].startswith('0x3593564c'), fixture['calldata'][:20]
"""
    pancake_v4_roundtrip_result = subprocess.run(
        [sys.executable, "-c", pancake_v4_roundtrip_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "pancake v4 roundtrip calldata fixture smoke test",
            pancake_v4_roundtrip_result.returncode == 0,
            pancake_v4_roundtrip_result.stderr.strip(),
        )
    )

    pancake_v4_roundtrip_fixture_verify = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_pancake_v4_roundtrip_fixture.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "pancake v4 roundtrip fixture matches reviewed ARX legs",
            pancake_v4_roundtrip_fixture_verify.returncode == 0,
            pancake_v4_roundtrip_fixture_verify.stderr.strip(),
        )
    )

    pancake_v4_roundtrip_call_code = """
from scripts.simulate_pancake_v4_roundtrip_call import MAX_UINT48, MAX_UINT160, pack_permit2_allowance, sellability_gate

packed = pack_permit2_allowance(MAX_UINT160, MAX_UINT48, 0)
assert packed == (MAX_UINT48 << 160) | MAX_UINT160, hex(packed)
packed_with_nonce = pack_permit2_allowance(1, 2, 3)
assert packed_with_nonce == (3 << 208) | (2 << 160) | 1, hex(packed_with_nonce)

success_gate = sellability_gate(
    'roundtrip_eth_call_success_no_recovery_rate',
    {'status': 'success', 'return': '0x'},
    {'status': 'unavailable'},
)
assert success_gate['gate'] == 'blocked_infinity_recovery_unverified', success_gate
assert success_gate['can_follow'] is False, success_gate
assert success_gate['can_sell_proven'] is False, success_gate
assert success_gate['recovery_rate'] is None, success_gate

verified_gate = sellability_gate(
    'roundtrip_eth_call_success_with_recovery_rate',
    {'status': 'success', 'return': '0x', 'recovery_rate': '0.995', 'quote_recovered_raw': '995', 'minimum_recovery_rate': '0.80'},
    {'status': 'skipped'},
)
assert verified_gate['gate'] == 'infinity_recovery_rate_verified', verified_gate
assert verified_gate['can_follow'] is True, verified_gate
assert verified_gate['can_sell_proven'] is True, verified_gate

low_gate = sellability_gate(
    'roundtrip_eth_call_success_with_recovery_rate',
    {'status': 'success', 'return': '0x', 'recovery_rate': '0.50', 'quote_recovered_raw': '500', 'minimum_recovery_rate': '0.80'},
    {'status': 'skipped'},
)
assert low_gate['gate'] == 'blocked_infinity_low_recovery', low_gate
assert low_gate['can_follow'] is False, low_gate

revert_gate = sellability_gate(
    'roundtrip_eth_call_reverted',
    {'status': 'reverted_or_failed', 'detail': 'execution reverted'},
    {'status': 'skipped'},
)
assert revert_gate['gate'] == 'blocked_infinity_roundtrip_failed', revert_gate
assert revert_gate['can_follow'] is False, revert_gate

readback_gate = sellability_gate('state_override_blocked', {}, {'status': 'skipped'})
assert readback_gate['gate'] == 'blocked_infinity_readback_failed', readback_gate
assert readback_gate['can_follow'] is False, readback_gate
"""
    pancake_v4_roundtrip_call_result = subprocess.run(
        [sys.executable, "-c", pancake_v4_roundtrip_call_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "pancake v4 roundtrip eth_call helper smoke test",
            pancake_v4_roundtrip_call_result.returncode == 0,
            pancake_v4_roundtrip_call_result.stderr.strip(),
        )
    )

    current_watchlist_ok = False
    current_watchlist_msg = ""
    try:
        current = json.loads((ROOT / "config" / "current_alpha_watchlist.json").read_text(encoding="utf-8"))
        items = current.get("items", [])
        o_item = next((item for item in items if item.get("symbol") == "O"), {})
        arx_item = next((item for item in items if item.get("symbol") == "ARX"), {})
        nes_item = next((item for item in items if item.get("symbol") == "NES"), {})
        current_watchlist_msg = (
            f"{len(items)} items, O active={o_item.get('active_monitoring')}, "
            f"ARX context={bool(arx_item.get('market_context'))}, NES pools={len(nes_item.get('pool_ids', []))}"
        )
        current_watchlist_ok = (
            len(items) > 0
            and o_item.get("active_monitoring") is False
            and bool(arx_item.get("market_context"))
            and bool(nes_item.get("contracts"))
            and bool(nes_item.get("pool_ids"))
        )
    except Exception as exc:
        current_watchlist_msg = str(exc)
    checks.append(("current alpha watchlist parses", current_watchlist_ok, current_watchlist_msg))

    server_run_ok = False
    server_run_msg = ""
    try:
        server_run_text = (ROOT / "scripts" / "server_run_once.sh").read_text(encoding="utf-8")
        opening_run = 'run_step "${ARX_OPENING_TIMEOUT_SECONDS'
        launch_run = 'run_step "${ARX_LAUNCH_TIMEOUT_SECONDS'
        arx_opening_before_launch = (
            opening_run in server_run_text
            and launch_run in server_run_text
            and server_run_text.index(opening_run) < server_run_text.index(launch_run)
        )
        arx_opening_refresh_guard = (
            "RUN_ARX_OPENING_REFRESH" in server_run_text
            and "skipped ARX opening refresh" in server_run_text
            and "arx_opening_sprint.sh" in server_run_text
        )
        arx_launch_guard = (
            "RUN_ARX_LAUNCH_WATCH" in server_run_text
            and "skipped ARX launch watch" in server_run_text
            and "arx_launch_watch.py" in server_run_text
        )
        intraday_run = "alpha_intraday_flow_watch.py"
        perp_run = "perp_oi_funding_watch.py"
        price_run = "alpha_price_momentum_watch.py"
        holder_run = "alpha_holder_concentration_watch.py"
        holder_context_order = (
            intraday_run in server_run_text
            and perp_run in server_run_text
            and price_run in server_run_text
            and holder_run in server_run_text
            and server_run_text.index(intraday_run) < server_run_text.index(perp_run) < server_run_text.index(price_run) < server_run_text.index(holder_run)
        )
        server_run_ok = (
            "flock -n" in server_run_text
            and "timeout" in server_run_text
            and "SNIPER_MONITOR_TIMEOUT_SECONDS" in server_run_text
            and "ALPHA_PROJECT_WATCH_TIMEOUT_SECONDS" in server_run_text
            and "ALPHA_PRELAUNCH_TIMEOUT_SECONDS" in server_run_text
            and "alpha_prelaunch_watch.py" in server_run_text
            and "ALPHA_OPENING_TIMEOUT_SECONDS" in server_run_text
            and "ALPHA_PRICE_MOMENTUM_TIMEOUT_SECONDS" in server_run_text
            and "alpha_price_momentum_watch.py" in server_run_text
            and "PERP_OI_FUNDING_TIMEOUT_SECONDS" in server_run_text
            and "perp_oi_funding_watch.py" in server_run_text
            and "SURF_AUX_MARKET_TIMEOUT_SECONDS" in server_run_text
            and "surf_aux_market_watch.py" in server_run_text
            and "EXTERNAL_AUX_SOURCE_TIMEOUT_SECONDS" in server_run_text
            and "external_aux_source_readiness.py" in server_run_text
            and "alpha_opening_sprint.sh" in server_run_text
            and "ARX_OPENING_TIMEOUT_SECONDS" in server_run_text
            and "arx_opening_sprint.sh" in server_run_text
            and "DISABLE_TELEGRAM" in server_run_text
            and "MONITOR_DISABLED_PROJECTS" in server_run_text
            and "step failed or timed out" in server_run_text
            and "RUN_O1_ATTRIBUTION" in server_run_text
            and arx_opening_refresh_guard
            and arx_launch_guard
            and arx_opening_before_launch
            and holder_context_order
        )
        server_run_msg = "lock+timeout+continue+O1 pause+ARX refresh/launch+perp+surf guarded+order present" if server_run_ok else "missing runtime guard"
    except Exception as exc:
        server_run_msg = str(exc)
    checks.append(("server run has overlap lock and timeouts", server_run_ok, server_run_msg))

    perp_watch_code = """
from scripts.perp_oi_funding_watch import best_ok_venue, classify_perp, listed_venue_names, total_open_interest, trend_for_symbol, venue_signal_notes

thin = classify_perp({'open_interest_usd': '1000', 'last_funding_rate': '0', 'quote_volume_24h': '0'})
assert thin['status'] == 'thin_or_unusable', thin
crowded = classify_perp({'open_interest_usd': '1000000', 'last_funding_rate': '0.001', 'quote_volume_24h': '10000', 'price_change_pct_24h': '1'})
assert crowded['status'] == 'crowded_funding', crowded
active = classify_perp({'open_interest_usd': '1000000', 'last_funding_rate': '0', 'quote_volume_24h': '2000000', 'price_change_pct_24h': '12'})
assert active['status'] == 'active_perp_market', active
quiet = classify_perp({'open_interest_usd': '1000000', 'last_funding_rate': '0', 'quote_volume_24h': '1000', 'price_change_pct_24h': '1'})
assert quiet['status'] == 'listed_quiet', quiet
history = [{
    'generated_at': '2026-06-30T00:00:00+00:00',
    'rows': [{
        'symbol': 'CAP',
        'status': 'ok',
        'mark_price': '0.02',
        'open_interest_usd': '1000000',
        'last_funding_rate': '0.0001',
    }],
}]
trend = trend_for_symbol(history, 'CAP', {'mark_price': '0.022', 'open_interest_usd': '1200000', 'last_funding_rate': '0.0002'}, '2026-06-30T01:00:00+00:00')
assert trend['trend_hint'] == '多头增量', trend
history_cross_venue = [{
    'generated_at': '2026-06-30T00:00:00+00:00',
    'rows': [{
        'symbol': 'GRAM',
        'perp_symbol': 'GRAM-USDT-SWAP',
        'status': 'ok',
        'mark_price': '0.02',
        'open_interest_usd': '1000000',
        'last_funding_rate': '0.0001',
    }],
}]
cross_venue_trend = trend_for_symbol(history_cross_venue, 'GRAM', {'perp_symbol': 'GRAMUSDT', 'mark_price': '0.022', 'open_interest_usd': '5000000', 'last_funding_rate': '0.0001'}, '2026-06-30T01:00:00+00:00')
assert cross_venue_trend['trend_status'] == 'no_history', cross_venue_trend
venues = [
    {'venue': 'okx_swap', 'status': 'ok', 'open_interest_usd': '2000000', 'last_funding_rate': '0.0006', 'direction_hint': '拥挤'},
    {'venue': 'bybit_linear', 'status': 'ok', 'open_interest_usd': '3000000', 'last_funding_rate': '0.0001', 'direction_hint': '可观察'},
]
assert best_ok_venue(venues)['venue'] == 'bybit_linear', venues
primary = {'venue': 'binance_usdm', 'open_interest_usd': '1000000'}
assert listed_venue_names(primary, venues) == ['binance_usdm', 'okx_swap', 'bybit_linear']
assert str(total_open_interest(primary, venues)) == '6000000'
notes = venue_signal_notes(venues)
assert len(notes) == 2 and 'okx_swap' in notes[0] and 'bybit_linear' in notes[1], notes
"""
    perp_watch_result = subprocess.run(
        [sys.executable, "-c", perp_watch_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("perp OI/funding classifier smoke test", perp_watch_result.returncode == 0, perp_watch_result.stderr.strip()))

    deploy_ok = False
    deploy_msg = ""
    try:
        deploy_text = (ROOT / "scripts" / "deploy_to_server.sh").read_text(encoding="utf-8")
        required_excludes = ["--exclude 'output/'", "--exclude 'reports/'", "--exclude 'logs/'", "--exclude '.env.local'", "--exclude '*.session'"]
        deploy_ok = all(item in deploy_text for item in required_excludes)
        deploy_msg = "runtime-state excludes present" if deploy_ok else "missing runtime-state exclude"
    except Exception as exc:
        deploy_msg = str(exc)
    checks.append(("deploy script preserves server runtime state", deploy_ok, deploy_msg))

    compile_cmd = [
        sys.executable,
        "-m",
        "py_compile",
        str(ROOT / "sniper_engine" / "scoring.py"),
        str(ROOT / "sniper_engine" / "local_sources.py"),
        str(ROOT / "sniper_engine" / "rpc.py"),
        str(ROOT / "sniper_engine" / "project_registry.py"),
        str(ROOT / "sniper_engine" / "address_labels.py"),
        str(ROOT / "sniper_engine" / "entity_clustering.py"),
        str(ROOT / "sniper_engine" / "exchange_aggregator.py"),
        str(ROOT / "scripts" / "sniper_score_local.py"),
        str(ROOT / "scripts" / "alpha_project_watch.py"),
        str(ROOT / "scripts" / "alpha_holder_concentration_watch.py"),
        str(ROOT / "scripts" / "alpha_prelaunch_watch.py"),
        str(ROOT / "scripts" / "alpha_opening_block_watch.py"),
        str(ROOT / "scripts" / "alpha_price_momentum_watch.py"),
        str(ROOT / "scripts" / "alpha_intraday_flow_watch.py"),
        str(ROOT / "scripts" / "verify_alpha_aggregator_trace.py"),
        str(ROOT / "scripts" / "collect_alpha_trace_bundle.py"),
        str(ROOT / "scripts" / "review_alpha_swap_samples.py"),
        str(ROOT / "scripts" / "review_alpha_swap_txs.py"),
        str(ROOT / "scripts" / "review_exchange_wallet_labels.py"),
        str(ROOT / "scripts" / "review_pancake_v4_samples.py"),
        str(ROOT / "scripts" / "x_mcp_readiness.py"),
        str(ROOT / "scripts" / "external_aux_source_readiness.py"),
        str(ROOT / "scripts" / "decode_pancake_v4_execute.py"),
        str(ROOT / "scripts" / "build_pancake_v4_roundtrip_fixture.py"),
        str(ROOT / "scripts" / "probe_pancake_v4_state_override.py"),
        str(ROOT / "scripts" / "simulate_pancake_v4_roundtrip_call.py"),
        str(ROOT / "scripts" / "arx_launch_watch.py"),
        str(ROOT / "scripts" / "arx_opening_block_watch.py"),
        str(ROOT / "scripts" / "build_alpha_daily_report.py"),
        str(ROOT / "scripts" / "prediction_market_watch.py"),
        str(ROOT / "scripts" / "telegram_signal_collector.py"),
        str(ROOT / "scripts" / "telegram_user_signal_collector.py"),
        str(ROOT / "scripts" / "telegram_user_login.py"),
        str(ROOT / "scripts" / "add_telegram_source.py"),
        str(ROOT / "scripts" / "analyze_pancake_pool_tx.py"),
        str(ROOT / "scripts" / "ingest_alpha_signal.py"),
        str(ROOT / "scripts" / "build_monitored_wallets.py"),
        str(ROOT / "scripts" / "o1_address_attribution.py"),
        str(ROOT / "scripts" / "sniper_monitor.py"),
        str(ROOT / "scripts" / "o1_block_verifier.py"),
        str(ROOT / "scripts" / "o1_decode_pancake_v3.py"),
        str(ROOT / "scripts" / "o1_trace_front_buyers.py"),
        str(ROOT / "scripts" / "summarize_hertzflow_skeleton.py"),
    ]
    compile_env = os.environ.copy()
    compile_env["PYTHONPYCACHEPREFIX"] = str(PYCACHE_DIR)
    compile_result = subprocess.run(compile_cmd, cwd=ROOT, env=compile_env, capture_output=True, text=True)
    checks.append(("python files compile", compile_result.returncode == 0, compile_result.stderr.strip()))

    holder_watch_code = """
import importlib.util
import json
import os
import tempfile
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_holder_concentration_watch', root / 'scripts' / 'alpha_holder_concentration_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.SURF_HOLDER_QUOTA_STATE_PATH = Path(tempfile.mkdtemp(prefix='surf_holder_quota_')) / 'quota.json'
token = '0x' + 'a' * 40
infra = '0x' + '1' * 40
holder_a = '0x' + '2' * 40
holder_b = '0x' + '3' * 40
holder_c = '0x' + '4' * 40
module.global_address_label = lambda chain, address: {'class': 'exchange_aggregator', 'label': 'Alpha Custody'} if address == infra else None
module.get_code = lambda chain, address, cache: '0x'
balances = {infra: 400, holder_a: 300, holder_b: 200, holder_c: 100}
raw_rows = module.top_rows(balances, 'bsc', token, 1000, 0, {}, effective=False)
effective_rows = module.top_rows(balances, 'bsc', token, 1000, 0, {}, effective=True)
assert str(module.pct_sum(raw_rows)) == '100', raw_rows
assert str(module.pct_sum(effective_rows)) == '60', effective_rows
assert raw_rows[0]['class'] == 'exchange_aggregator', raw_rows
signal = module.classify_signal(
    {'effective_top10_pct': '60', 'effective_top10_delta_pct': '-2', 'raw_top10_pct': '100', 'raw_top10_delta_pct': '0', 'raw_top10_infra_pct': '40', 'raw_top10_infra_delta_pct': '0'},
    {'effective_top10_pct': '62', 'raw_top10_pct': '100', 'raw_top10_infra_pct': '40'},
)
assert signal['direction'] == 'effective_top10_down', signal
assert '持仓降风险' in signal['action'], signal
baseline = module.classify_signal({'effective_top10_pct': '60'}, None)
assert baseline['direction'] == 'baseline', baseline
class FakeSurfResult:
    returncode = 0
    stderr = ''
    stdout = json.dumps({
        'data': [
            {'address': infra, 'balance': '400', 'percentage': 40, 'entity_name': 'Binance Wallet', 'entity_type': 'misc'},
            {'address': holder_a, 'balance': '300', 'percentage': 30, 'entity_name': None, 'entity_type': None},
            {'address': holder_b, 'balance': '200', 'percentage': 20, 'entity_name': 'PancakeSwap', 'entity_type': 'dex'},
            {'address': holder_c, 'balance': '100', 'percentage': 10, 'entity_name': None, 'entity_type': None},
        ],
        'meta': {'credits_used': 0},
    })

def fake_surf_run(*args, **kwargs):
    return FakeSurfResult()

module.subprocess.run = fake_surf_run
module.surf_cli = lambda: 'surf'
os.environ['ALPHA_HOLDER_FULL_SOURCE'] = 'surf'
surf_status = module.full_holder_source_status('bsc', token)
os.environ.pop('ALPHA_HOLDER_FULL_SOURCE', None)
assert surf_status['status'] == 'ok', surf_status
assert 'Surf全量Top10 100.00%' in surf_status['summary'], surf_status
assert '交易所/DEX/托管约 60.00%' in surf_status['summary'], surf_status
class FakeSurfQuotaResult:
    returncode = 4
    stderr = ''
    stdout = json.dumps({'error': {'code': 'FREE_QUOTA_EXHAUSTED', 'message': 'free daily credit exhausted'}})

module.subprocess.run = lambda *args, **kwargs: FakeSurfQuotaResult()
os.environ['ALPHA_HOLDER_FULL_SOURCE'] = 'surf'
quota_status = module.full_holder_source_status('bsc', token)
os.environ.pop('ALPHA_HOLDER_FULL_SOURCE', None)
assert quota_status['status'] == 'FREE_QUOTA_EXHAUSTED', quota_status
assert 'Surf免费额度已用完' in quota_status['summary'], quota_status
def should_not_call_surf(*args, **kwargs):
    raise AssertionError('quota cache should block surf subprocess call')

module.subprocess.run = should_not_call_surf
os.environ['ALPHA_HOLDER_FULL_SOURCE'] = 'surf'
cached_quota_status = module.full_holder_source_status('bsc', token)
os.environ.pop('ALPHA_HOLDER_FULL_SOURCE', None)
assert cached_quota_status['status'] == 'FREE_QUOTA_EXHAUSTED', cached_quota_status
assert '今日不再请求' in cached_quota_status['summary'], cached_quota_status
bearish_market_context = {
    'price': {'TEST': {'stale': False, 'age_minutes': 5, 'analysis': {'direction': '放量走弱', 'trade_signal': 'Alpha 放量收跌；卖出/减仓观察'}}},
    'flow': {'TEST': {'stale': False, 'age_minutes': 5, 'analysis': {'direction': '偏空', 'trade_signal': '卖出/减仓；盘中大额净卖出'}}},
}
holder_project = {
    'symbol': 'TEST',
    'priority': 'P1_MONITOR',
    'chain': 'bsc',
    'address': token,
    'complete_holder_reconstruction': False,
    'log_count': 3,
    'metrics': {
        'effective_top10_pct': '60',
        'effective_top10_delta_pct': '-2',
        'raw_top10_pct': '100',
        'raw_top10_delta_pct': '0',
        'raw_top10_infra_pct': '40',
    },
    'full_holder_source': surf_status,
    'signal': signal,
}
holder_project['decision_context'] = module.holder_decision_context(holder_project, bearish_market_context)
assert '偏空确认' in holder_project['decision_context']['action'], holder_project
up_project = {
    **holder_project,
    'signal': {'direction': 'effective_top10_up', 'action': '吸筹观察；等价格承接和净买确认', 'reason': 'test', 'level': 'HIGH'},
    'metrics': {**holder_project['metrics'], 'effective_top10_delta_pct': '2'},
}
up_project['decision_context'] = module.holder_decision_context(up_project, {'price': {}, 'flow': {}})
assert '吸筹观察' in up_project['decision_context']['action'], up_project
text = module.telegram_text({
    'generated_at': '2026-07-03T00:00:00+00:00',
    'project_count': 1,
    'alert_count': 1,
    'projects': [holder_project],
})
assert '有效总结' in text, text
assert '统一结论在文末' in text, text
assert '联动判断: 偏空确认；持仓减仓/离场，空仓不接' in text, text
assert '排除托管后前十' in text, text
assert '窗口重建前十' in text, text
assert '外部全量Top10' in text, text
assert 'Surf全量Top10 100.00%' in text, text
assert '较上次减少 2.00 个百分点' in text, text
summary_idx = text.rfind('项目总结汇总:')
assert summary_idx > text.find('外部全量Top10'), text
assert text.count('项目总结汇总:') == 1, text
assert 'TEST: 偏空确认；持仓减仓/离场，空仓不接' in text[summary_idx:], text
assert '有效前十' not in text and '原始前十' not in text, text
print(f"raw={module.pct_sum(raw_rows)} effective={module.pct_sum(effective_rows)} signal={signal['direction']}")
"""
    holder_watch = subprocess.run(
        [sys.executable, "-c", holder_watch_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    holder_watch_ok = holder_watch.returncode == 0
    holder_watch_msg = holder_watch.stdout.strip() or holder_watch.stderr.strip()
    checks.append(("holder concentration excludes infrastructure and flags downtrend", holder_watch_ok, holder_watch_msg))

    alpha_intraday_cex_code = """
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_intraday_flow_watch', root / 'scripts' / 'alpha_intraday_flow_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.now_utc = lambda: datetime(2026, 7, 2, 8, 12, tzinfo=timezone.utc)
event = {
    'symbol': 'TEST',
    'chain': 'bsc',
    'token': {'address': '0x' + 'a' * 40, 'symbol': 'TEST', 'decimals': 18},
    'quote': {'address': '0x' + 'b' * 40, 'symbol': 'USDT', 'decimals': 18},
    'market_context': {'observed_binance_alpha_price_usdt': '0.05'},
    'cex_deposit_addresses': ['0x' + 'c' * 40],
    'cex_addresses': ['0x' + 'd' * 40],
    'known_contracts': [],
}
module.opening.has_contract_code = lambda chain, address: False
transfers = [
    {'token': event['token']['address'], 'from': '0x' + '1' * 40, 'to': '0x' + 'c' * 40, 'amount': module.Decimal('300000')},
    {'token': event['token']['address'], 'from': '0x' + '2' * 40, 'to': '0x' + '3' * 40, 'amount': module.Decimal('1')},
]
cex_rows = module.cex_deposit_transfers(event, transfers)
assert len(cex_rows) == 1, cex_rows
candidate = '0x' + 'e' * 40
runtime_rows = module.cex_deposit_transfers(
    event,
    [{'token': event['token']['address'], 'from': '0x' + '6' * 40, 'to': candidate, 'amount': module.Decimal('150000')}],
    {candidate: {'address': candidate, 'class': 'cex_deposit_candidate'}},
)
assert len(runtime_rows) == 1 and runtime_rows[0]['class'] == 'cex_deposit_candidate', runtime_rows
runtime_analysis = module.analyze_rows(
    event,
    [{'cex_token_deposit': '150000', 'cex_quote_estimate': '7500', 'cex_deposit_count': 1, 'runtime_cex_deposit_candidate_count': 1, 'cex_destination_classes': 'cex_deposit_candidate'}],
    100,
    200,
    2,
    2,
)
assert runtime_analysis['runtime_cex_deposit_candidate_count'] == 1, runtime_analysis
assert runtime_analysis['cex_destination_classes'] == 'cex_deposit_candidate', runtime_analysis
assert '候选CEX充值路径' in runtime_analysis['trade_signal'], runtime_analysis
real_get_logs = module.opening.get_logs_quick
def fake_get_logs(chain, query, chunk_blocks, max_logs, timeout):
    user = '0x' + '7' * 40
    hot = '0x' + 'd' * 40
    amount = hex(200000 * 10**18)
    return [
        {
            'address': event['token']['address'],
            'topics': [module.opening.TRANSFER_TOPIC, module.opening.address_topic(user), module.opening.address_topic(candidate)],
            'data': amount,
            'blockNumber': hex(101),
            'transactionIndex': '0x1',
            'logIndex': '0x1',
            'transactionHash': '0x' + 'a' * 64,
        },
        {
            'address': event['token']['address'],
            'topics': [module.opening.TRANSFER_TOPIC, module.opening.address_topic(candidate), module.opening.address_topic(hot)],
            'data': amount,
            'blockNumber': hex(102),
            'transactionIndex': '0x1',
            'logIndex': '0x2',
            'transactionHash': '0x' + 'b' * 64,
        },
    ]
module.opening.get_logs_quick = fake_get_logs
runtime_candidates = module.runtime_cex_deposit_candidates(event, 100, 200)
module.opening.get_logs_quick = real_get_logs
assert candidate in runtime_candidates, runtime_candidates
assert runtime_candidates[candidate]['destination_classes'] == ['cex_deposit'], runtime_candidates
analysis = module.analyze_rows(
    event,
    [{'cex_token_deposit': '300000', 'cex_quote_estimate': '15000', 'cex_deposit_count': 1}],
    100,
    200,
    2,
    2,
)
assert analysis['direction'] == '偏空', analysis
assert '代币进入CEX' in analysis['trade_signal'], analysis
assert analysis['spot_action'] == '持仓降风险；空仓不追', analysis
assert analysis['cex_quote_estimate'] == '15000', analysis
event_a = {**event, 'from_block': 100, 'to_block': 200, 'analysis': analysis}
event_b = {**event, 'from_block': 120, 'to_block': 220, 'analysis': analysis}
assert module.event_alert_keys(event_a) == module.event_alert_keys(event_b), (module.event_alert_keys(event_a), module.event_alert_keys(event_b))
text = module.telegram_text({'events': [event_a], 'new_alert_count': 1})
assert 'CEX预出货' in text and '持仓降风险' in text and '❗TEST' in text and '买卖信号: ❗' in text, text
buy_analysis = module.analyze_rows(
    event,
    [{'buyer': '0x' + '4' * 40, 'spent_quote': '25000', 'cex_token_deposit': '0', 'cex_quote_estimate': '0', 'cex_deposit_count': 0}],
    100,
    200,
    1,
    1,
)
buy_text = module.telegram_text({'events': [{**event, 'analysis': buy_analysis}], 'new_alert_count': 1})
assert buy_analysis['direction'] == '观察偏多', buy_analysis
assert '❗TEST' in buy_text and '买卖信号: ❗盘中大额净买入' in buy_text, buy_text
module.BLOCK_TX_CACHE.clear()
real_quick_rpc = module.opening.quick_rpc_call
def fake_quick_rpc(chain, method, params, timeout):
    if method == 'eth_getBlockByNumber':
        return {
            'transactions': [
                {'from': '0x' + 'd' * 40, 'to': '0x' + '1' * 40, 'value': hex(2 * 10**15), 'hash': '0x' + '9' * 64},
                {'from': '0x' + '5' * 40, 'to': '0x' + '1' * 40, 'value': hex(5 * 10**15), 'hash': '0x' + '8' * 64},
            ]
        }
    return real_quick_rpc(chain, method, params, timeout)
module.opening.quick_rpc_call = fake_quick_rpc
gas_rows = module.cex_gas_priming_transfers(event, {'0x' + '1' * 40}, 150)
module.opening.quick_rpc_call = real_quick_rpc
assert len(gas_rows) == 1 and gas_rows[0]['amount_bnb'] == module.Decimal('0.002'), gas_rows
gas_analysis = module.analyze_rows(
    event,
    [{'cex_token_deposit': '300000', 'cex_quote_estimate': '15000', 'cex_deposit_count': 1, 'cex_gas_priming_count': 1, 'cex_gas_priming_bnb': '0.002'}],
    100,
    200,
    2,
    2,
)
gas_text = module.telegram_text({'events': [{**event, 'analysis': gas_analysis}], 'new_alert_count': 1})
assert 'CEX打gas后代币进入CEX充值/热钱包' in gas_analysis['trade_signal'], gas_analysis
assert 'CEX打gas≈0.002 BNB / 1 次' in gas_text and '买卖信号: ❗' in gas_text, gas_text
"""
    alpha_intraday_cex_result = subprocess.run(
        [sys.executable, "-c", alpha_intraday_cex_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha intraday CEX pending-sell detection and dedupe",
            alpha_intraday_cex_result.returncode == 0,
            alpha_intraday_cex_result.stderr.strip(),
        )
    )

    x_mcp_readiness_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
out = Path(tempfile.mkdtemp(prefix='x_mcp_readiness_'))
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'x_mcp_readiness.py'),
        '--out-dir',
        str(out),
        '--no-network',
        '--skip-xurl',
    ],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out / 'latest.json').read_text(encoding='utf-8'))
assert payload['schema'] == 'x_mcp_readiness.v1', payload
assert payload['status'] == 'offline_probe', payload
assert payload['network']['skipped'] is True, payload
assert payload['xurl']['skipped'] is True, payload
assert (out / 'latest.md').exists(), out
"""
    x_mcp_readiness_result = subprocess.run(
        [sys.executable, "-c", x_mcp_readiness_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("x mcp readiness offline smoke test", x_mcp_readiness_result.returncode == 0, x_mcp_readiness_result.stderr.strip()))

    external_aux_readiness_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
out = Path(tempfile.mkdtemp(prefix='external_aux_sources_'))
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'external_aux_source_readiness.py'),
        '--out-dir',
        str(out),
    ],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out / 'latest.json').read_text(encoding='utf-8'))
assert payload['schema'] == 'external_aux_source_readiness.v1', payload
assert payload['source_count'] >= 4, payload
ids = {row['id'] for row in payload['rows']}
assert {'coinglass', 'coinank', 'gmgn', 'debot_ai'}.issubset(ids), payload
assert all(row['authority'] == 'context_only' for row in payload['rows'] if not row['live_probe_validated']), payload
assert (out / 'latest.md').exists(), out
"""
    external_aux_readiness_result = subprocess.run(
        [sys.executable, "-c", external_aux_readiness_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "external auxiliary source readiness smoke test",
            external_aux_readiness_result.returncode == 0,
            external_aux_readiness_result.stderr.strip(),
        )
    )

    celue_audit_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
out = Path(tempfile.mkdtemp(prefix='celue_audit_'))
source_skill = Path('/Users/xuyufan/Documents/蒸馏技能/celue')
installed_skill = Path('/Users/xuyufan/.codex/skills/celue')
cmd = [
    sys.executable,
    str(root / 'scripts' / 'audit_celue_integration.py'),
    '--out-dir',
    str(out),
]
if not (source_skill.exists() and installed_skill.exists()):
    cmd.append('--project-only')
result = subprocess.run(
    cmd,
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr or result.stdout
payload = json.loads((out / 'latest.json').read_text(encoding='utf-8'))
assert payload['schema'] == 'celue_integration_audit.v1', payload
assert payload['failed_count'] == 0, payload
assert payload['check_count'] >= 10, payload
assert (out / 'latest.md').exists(), out
"""
    celue_audit_result = subprocess.run(
        [sys.executable, "-c", celue_audit_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "celue integration audit smoke test",
            celue_audit_result.returncode == 0,
            celue_audit_result.stderr.strip() or celue_audit_result.stdout.strip(),
        )
    )

    registry_env = os.environ.copy()
    registry_env["PROJECT_REGISTRY_PATH"] = str(Path(tempfile.gettempdir()) / "sniper_project_registry_test.json")
    registry_env["PROJECT_REGISTRY_SUMMARY_PATH"] = str(Path(tempfile.gettempdir()) / "sniper_project_registry_test.md")
    registry_test_code = """
from pathlib import Path
from scripts.ingest_alpha_signal import parse_signal
from sniper_engine.project_registry import merge_signal, read_json, REGISTRY_PATH, SUMMARY_PATH

for path in [REGISTRY_PATH, SUMMARY_PATH]:
    path.unlink(missing_ok=True)

text1 = '$BTC 即将上线\\n区块: 123456\\nBSC 合约: 0x1111111111111111111111111111111111111111'
text2 = '$BTC 总量 1B\\n团队 10%\\n流动性 6%'
first = merge_signal(parse_signal(text1, Path('/tmp/btc1.txt')), {'collector': 'verify', 'source': 'one'})
second = merge_signal(parse_signal(text2, Path('/tmp/btc2.txt')), {'collector': 'verify', 'source': 'two'})
third = merge_signal(parse_signal(text2, Path('/tmp/btc2.txt')), {'collector': 'verify', 'source': 'two'})
cap_text = '''LP / USDT
CAP 合约: 0x99991c6aabba5a096f24f250b73580f5179b9999
hook: 0xb0baa371b899950b4ef6a27c21baf5ef7c434d0f
PoolId: 0x3bca91b9b847cff6f4b666fa1d966981678975e13fd69d647bd11bed99f5fa14'''
cap_bad = parse_signal(cap_text, Path('/tmp/cap_pool_bad.txt'))
cap_bad['symbol'] = 'LP'
cap_first = merge_signal(cap_bad, {'collector': 'verify', 'source': 'cap_bad'})
cap_good = parse_signal(cap_text, Path('/tmp/cap_pool_good.txt'))
cap_good['symbol'] = 'CAP'
cap_second = merge_signal(cap_good, {'collector': 'verify', 'source': 'cap_good'})
registry = read_json(REGISTRY_PATH, {})
projects = registry.get('projects', [])
assert first['status'] == 'new_project', first
assert second['status'] == 'updated_project', second
assert third['status'] == 'duplicate_signal', third
assert cap_first['project_key'] == 'contract:0x99991c6aabba5a096f24f250b73580f5179b9999', cap_first
assert cap_second['project_key'] == 'contract:0x99991c6aabba5a096f24f250b73580f5179b9999', cap_second
assert len(projects) == 2, projects
btc = next(project for project in projects if project['symbol'] == 'BTC')
cap = next(project for project in projects if project['symbol'] == 'CAP')
assert btc['facts']['total_supply'] == '1B', btc['facts']
assert cap['project_key'] == 'contract:0x99991c6aabba5a096f24f250b73580f5179b9999', cap
assert cap['symbol'] == 'CAP', cap
assert any(row.get('address', '').lower() == '0x99991c6aabba5a096f24f250b73580f5179b9999' for row in cap.get('contracts', [])), cap
"""
    registry_result = subprocess.run(
        [sys.executable, "-c", registry_test_code],
        cwd=ROOT,
        env=registry_env,
        capture_output=True,
        text=True,
    )
    checks.append(("project registry dedup smoke test", registry_result.returncode == 0, registry_result.stderr.strip()))

    parser_test_code = """
from pathlib import Path
from scripts.ingest_alpha_signal import parse_signal

text = '''18点空投 (ARX）
分数要求：225分 先到先得 每人172个代币
代币合约：0xd5f6ef5dEabE61E6d5CDB49BFB6f156F2c1cA715
Alpha空投占代币总量的0.85%'''
parsed = parse_signal(text, Path('/tmp/arx_airdrop.txt'))
assert parsed['symbol'] == 'ARX', parsed
assert parsed['addresses'][0]['label_hint'] == 'token_contract', parsed['addresses']
"""
    parser_result = subprocess.run(
        [sys.executable, "-c", parser_test_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("signal parser handles parenthesized ARX", parser_result.returncode == 0, parser_result.stderr.strip()))

    clustering_guard_code = """
from sniper_engine.entity_clustering import can_use_as_funding_cluster_parent, cluster_by_funding_source

extra = {
    '0x' + '1' * 40: {'class': 'cex_hot_wallet'},
    '0x' + '2' * 40: {'class': 'cex_deposit'},
    '0x' + '3' * 40: {'class': 'bridge'},
    '0x' + '4' * 40: {'class': 'unknown_contract_pending_bearish'},
    '0x' + '5' * 40: {'class': 'eoa'},
}
assert not can_use_as_funding_cluster_parent('bsc', '0x' + '1' * 40, extra)
assert not can_use_as_funding_cluster_parent('bsc', '0x' + '2' * 40, extra)
assert not can_use_as_funding_cluster_parent('bsc', '0x' + '3' * 40, extra)
assert not can_use_as_funding_cluster_parent('bsc', '0x' + '4' * 40, extra)
assert can_use_as_funding_cluster_parent('bsc', '0x' + '5' * 40, extra)
assert can_use_as_funding_cluster_parent('bsc', '0x' + '6' * 40, extra)
rows = [
    {'address': '0x' + 'a' * 40, 'funding_source': '0x' + '5' * 40},
    {'address': '0x' + 'b' * 40, 'funding_source': '0x' + '5' * 40},
    {'address': '0x' + 'c' * 40, 'funding_source': '0x' + '1' * 40},
    {'address': '0x' + 'd' * 40, 'funding_source': '0x' + '1' * 40},
]
review = cluster_by_funding_source('bsc', rows, extra)
assert review['cluster_count'] == 1, review
assert review['clusters'][0]['member_count'] == 2, review
assert review['skipped_parent_count'] == 1, review
assert review['skipped_parents'][0]['class'] == 'cex_hot_wallet', review
"""
    clustering_guard_result = subprocess.run(
        [sys.executable, "-c", clustering_guard_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("funding-source clustering guard", clustering_guard_result.returncode == 0, clustering_guard_result.stderr.strip()))

    funding_cluster_review_code = """
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='funding_cluster_review_'))
source = work / 'clusters.csv'
labels = work / 'labels.json'
out_dir = work / 'out'
rows = [
    {'address': '0x' + 'a' * 40, 'funding_source': '0x' + '5' * 40},
    {'address': '0x' + 'b' * 40, 'funding_source': '0x' + '5' * 40},
    {'address': '0x' + 'c' * 40, 'funding_source': '0x' + '1' * 40},
    {'address': '0x' + 'd' * 40, 'funding_source': '0x' + '1' * 40},
]
with source.open('w', encoding='utf-8', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=['address', 'funding_source'])
    writer.writeheader()
    writer.writerows(rows)
labels.write_text(json.dumps({'0x' + '1' * 40: 'cex_hot_wallet'}), encoding='utf-8')
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'review_funding_source_clusters.py'),
        '--input',
        str(source),
        '--extra-labels',
        str(labels),
        '--out-dir',
        str(out_dir),
    ],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert payload['cluster_count'] == 1, payload
assert payload['skipped_parent_count'] == 1, payload
assert payload['skipped_parents'][0]['class'] == 'cex_hot_wallet', payload
assert (out_dir / 'latest.md').exists(), out_dir
"""
    funding_cluster_review_result = subprocess.run(
        [sys.executable, "-c", funding_cluster_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("funding-source cluster review smoke test", funding_cluster_review_result.returncode == 0, funding_cluster_review_result.stderr.strip()))

    opening_funder_review_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
work = Path(tempfile.mkdtemp(prefix='opening_funder_review_'))
source = work / 'opening.json'
out_dir = work / 'out'
source.write_text(json.dumps({
    'events': [
        {
            'symbol': 'TEST',
            'name': 'Test Token',
            'rows': [
                {'buyer': '0x' + 'a' * 40, 'block': 123, 'tx': '0x' + '1' * 64, 'spent_quote': '100'},
                {'buyer': '0x' + 'b' * 40, 'block': 124, 'tx': '0x' + '2' * 64, 'spent_quote': '200'},
            ],
        }
    ]
}), encoding='utf-8')
result = subprocess.run(
    [
        sys.executable,
        str(root / 'scripts' / 'review_opening_cohort_funders.py'),
        '--input',
        str(source),
        '--out-dir',
        str(out_dir),
        '--lookback-blocks',
        '0',
    ],
    cwd=root,
    capture_output=True,
    text=True,
)
assert result.returncode == 0, result.stderr
payload = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
assert payload['funders_found'] == 0, payload
assert len(payload['rows']) == 2, payload
assert payload['rows'][0]['symbol'] == 'TEST', payload
assert (out_dir / 'latest.md').exists(), out_dir
"""
    opening_funder_review_result = subprocess.run(
        [sys.executable, "-c", opening_funder_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("opening cohort funder review smoke test", opening_funder_review_result.returncode == 0, opening_funder_review_result.stderr.strip()))

    alpha_venue_code = """
from decimal import Decimal
import os
from scripts.alpha_price_momentum_watch import venue_classification

cap = venue_classification(Decimal('869294.19'), {'status': 'ok', 'onchain_gross_quote': '37699.91'})
assert cap['venue_class'] == 'ALPHA_DOMINANT', cap
assert cap['coverage'] == 'ONCHAIN_NETFLOW_UNRELIABLE', cap
assert cap['onchain_netflow_reliable'] is False, cap
os.environ['ONCHAIN_NETFLOW_RELIABLE_WHEN_ALPHA_DOMINANT'] = '1'
cap_reliable = venue_classification(Decimal('869294.19'), {'status': 'ok', 'onchain_gross_quote': '37699.91'})
assert cap_reliable['coverage'] == 'ONCHAIN_PARTIAL_NEGATIVE_ONLY', cap_reliable
assert cap_reliable['onchain_netflow_reliable'] is True, cap_reliable
os.environ.pop('ONCHAIN_NETFLOW_RELIABLE_WHEN_ALPHA_DOMINANT', None)
mixed = venue_classification(Decimal('300000'), {'status': 'ok', 'onchain_gross_quote': '100000'})
assert mixed['venue_class'] == 'MIXED', mixed
native = venue_classification(Decimal('100000'), {'status': 'ok', 'onchain_gross_quote': '70000'})
assert native['venue_class'] == 'ONCHAIN_NATIVE', native
missing = venue_classification(Decimal('100000'), {'status': 'missing', 'onchain_gross_quote': '0'})
assert missing['venue_class'] == 'UNKNOWN', missing
"""
    alpha_venue_result = subprocess.run(
        [sys.executable, "-c", alpha_venue_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("alpha venue classification guard", alpha_venue_result.returncode == 0, alpha_venue_result.stderr.strip()))

    exchange_aggregator_exclusion_code = """
from scripts.alpha_opening_block_watch import excluded_addresses

event = {
    'chain': 'bsc',
    'token': {'address': '0x' + 'a' * 40},
    'quote': {'address': '0x' + 'b' * 40},
    'hook': '',
    'operator': '',
    'known_contracts': [],
    'exchange_aggregator_addresses': ['0x' + '1' * 40],
    'exchange_aggregator_suspect_addresses': [{'address': '0x' + '2' * 40}],
    'market_context': {
        'exchange_rebalance_addresses': ['0x' + '3' * 40],
        'pool_manager_addresses': ['0x' + '4' * 40],
    },
}
excluded = excluded_addresses(event)
assert '0x' + '1' * 40 in excluded, excluded
assert '0x' + '2' * 40 in excluded, excluded
assert '0x' + '3' * 40 in excluded, excluded
assert '0x' + '4' * 40 in excluded, excluded
"""
    exchange_aggregator_exclusion_result = subprocess.run(
        [sys.executable, "-c", exchange_aggregator_exclusion_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "exchange aggregator cohort exclusion guard",
            exchange_aggregator_exclusion_result.returncode == 0,
            exchange_aggregator_exclusion_result.stderr.strip(),
        )
    )

    exchange_aggregator_classifier_code = """
from sniper_engine.exchange_aggregator import classify_market_flow_effect, score_exchange_aggregator_candidate

infra = score_exchange_aggregator_candidate({
    'shared_across_tokens': 8,
    'paired_custody_structure': True,
})
assert infra['classification'] == 'exchange_aggregator_suspect', infra
assert infra['has_mechanism_fingerprint'] is True, infra
assert infra['exclude_from_cohort'] is True, infra
assert infra['action'] == 'manual_confirm_then_allowlist', infra

allowlist_empty_structural = score_exchange_aggregator_candidate({
    'shared_across_tokens': 12,
    'paired_custody_structure': True,
    'shared_binance_wallet_router': True,
})
assert allowlist_empty_structural['classification'] == 'exchange_aggregator_suspect', allowlist_empty_structural
assert allowlist_empty_structural['signals'] == ['cross_token_reuse', 'paired_custody_structure', 'shared_binance_wallet_router'], allowlist_empty_structural

mm_like = score_exchange_aggregator_candidate({
    'bidirectional_high_frequency_net_flat': True,
    'contract_direct_pool_non_terminal': True,
})
assert mm_like['classification'] == 'mm_or_project_suspect', mm_like
assert mm_like['has_mechanism_fingerprint'] is False, mm_like
assert mm_like['exclude_from_cohort'] is False, mm_like

weak = score_exchange_aggregator_candidate({'shared_across_tokens': 2})
assert weak['classification'] == 'unknown', weak

sell = classify_market_flow_effect('exchange_aggregator', confirmed_dex_sell=True)
assert sell['market_effect'] == 'bearish_confirmed_dex_sell', sell
assert sell['action'] == 'keep_bearish_signal', sell

rebalance = classify_market_flow_effect('exchange_aggregator')
assert rebalance['market_effect'] == 'exchange_rebalance_reference', rebalance
assert rebalance['cohort_effect'] == 'exclude_from_cohort', rebalance

project = classify_market_flow_effect('mm_or_project_suspect')
assert project['market_effect'] == 'transfer_only_neutral_watch', project
assert project['action'] == 'trace_next_hop_before_sell_claim', project
"""
    exchange_aggregator_classifier_result = subprocess.run(
        [sys.executable, "-c", exchange_aggregator_classifier_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "exchange aggregator mechanism classifier guard",
            exchange_aggregator_classifier_result.returncode == 0,
            exchange_aggregator_classifier_result.stderr.strip(),
        )
    )

    alpha_aggregator_trace_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
token = '0x' + 'a' * 40
quote = '0x' + 'b' * 40
router = '0x' + 'c' * 40
stable = '0x' + '1' * 40
alt = '0x' + '2' * 40
user = '0x' + '3' * 40
pool = '0x' + '4' * 40
usdc = '0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d'

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    main = {
        'transfers': [
            {'token': quote, 'from': user, 'to': stable, 'amount': '100'},
            {'token': quote, 'from': stable, 'to': router, 'amount': '100'},
            {'token': usdc, 'from': user, 'to': stable, 'amount': '50'},
            {'token': usdc, 'from': stable, 'to': router, 'amount': '50'},
            {'token': usdc, 'from': router, 'to': pool, 'amount': '50'},
            {'token': token, 'from': pool, 'to': alt, 'amount': '1000'},
            {'token': token, 'from': alt, 'to': user, 'amount': '1000'},
        ],
        'calls': [
            {'from': stable, 'to': router},
            {'from': alt, 'to': router},
            {'from': router, 'to': pool},
        ],
    }
    main_path = tmp_path / 'trace_main.json'
    main_path.write_text(json.dumps(main), encoding='utf-8')
    history_paths = []
    for idx in range(6):
        hist_token = '0x' + format(idx + 10, '040x')
        hist = {
            'transfers': [
                {'token': hist_token, 'from': pool, 'to': alt, 'amount': '1'},
                {'token': hist_token, 'from': alt, 'to': user, 'amount': '1'},
            ],
            'calls': [{'from': alt, 'to': router}],
        }
        path = tmp_path / f'history_{idx}.json'
        path.write_text(json.dumps(hist), encoding='utf-8')
        history_paths.append(path)
    cmd = [
        sys.executable,
        str(root / 'scripts' / 'verify_alpha_aggregator_trace.py'),
        '--input',
        str(main_path),
        '--token',
        'auto',
        '--quote',
        quote,
        '--router',
        router,
        '--history',
        *[str(path) for path in history_paths],
    ]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['dry_run'] is True and report['config_write'] is False, report
    assert report['manual_review_required'] is True, report
    assert report['token'] == token, report
    assert report['quote'] == quote, report
    assert report['trace_quality']['distinct_alpha_tokens'] >= 3, report['trace_quality']
    assert report['trace_quality']['warnings'] == [], report['trace_quality']
    assert report['leg_summary']['user_quote_to_stable_custody'] == 1, report['leg_summary']
    assert report['leg_summary']['quote_custody_to_router'] == 1, report['leg_summary']
    assert report['leg_summary']['token_router_or_pool_leg'] == 1, report['leg_summary']
    assert report['leg_summary']['alt_custody_token_out'] == 1, report['leg_summary']
    assert pool in report['roles']['pool_or_external_candidates'], report['roles']
    assert pool not in report['roles']['alt_custody_candidates'], report['roles']
    candidates = {row['address']: row for row in report['candidates']}
    assert router in candidates, candidates
    assert candidates[router]['classification'] == 'exchange_aggregator_suspect', candidates[router]
    assert candidates[alt]['classification'] == 'exchange_aggregator_suspect', candidates[alt]
    assert candidates[alt]['shared_across_tokens'] >= 5, candidates[alt]
"""
    alpha_aggregator_trace_result = subprocess.run(
        [sys.executable, "-c", alpha_aggregator_trace_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha aggregator trace dry-run verifier",
            alpha_aggregator_trace_result.returncode == 0,
            alpha_aggregator_trace_result.stderr.strip() or alpha_aggregator_trace_result.stdout.strip(),
        )
    )

    trace_bundle_collector_code = """
from scripts.collect_alpha_trace_bundle import (
    build_bundle,
    call_edges_from_call_tracer,
    call_edges_from_trace_transaction,
    parse_transfer_logs,
)

tx_hash = '0x' + 'a' * 64
token = '0x' + '1' * 40
sender = '0x' + '2' * 40
recipient = '0x' + '3' * 40
router = '0x' + '4' * 40
pool = '0x' + '5' * 40

def topic(address):
    return '0x' + ('0' * 24) + address[2:]

receipt = {
    'blockNumber': '0x7b',
    'transactionIndex': '0x5',
    'status': '0x1',
    'from': sender,
    'to': router,
    'gasUsed': '0x5208',
    'effectiveGasPrice': '0x3b9aca00',
    'logs': [
        {
            'address': token,
            'topics': [
                '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
                topic(sender),
                topic(recipient),
            ],
            'data': '0x' + hex(1000)[2:].rjust(64, '0'),
            'logIndex': '0x0',
        }
    ],
}
tx = {'hash': tx_hash, 'blockNumber': '0x7b', 'transactionIndex': '0x5', 'from': sender, 'to': router, 'value': '0x0', 'input': '0x1234'}
transfers = parse_transfer_logs(receipt, tx_hash)
assert len(transfers) == 1, transfers
assert transfers[0]['token'] == token and transfers[0]['from'] == sender and transfers[0]['to'] == recipient, transfers
assert transfers[0]['amount'] == '1000', transfers

trace = {'from': sender, 'to': router, 'type': 'CALL', 'calls': [{'from': router, 'to': pool, 'type': 'CALL'}]}
call_edges = call_edges_from_call_tracer(trace)
assert len(call_edges) == 2 and call_edges[0]['source'] == 'debug_callTracer', call_edges
parity_edges = call_edges_from_trace_transaction([{'type': 'call', 'action': {'from': router, 'to': pool, 'callType': 'call', 'value': '0x0'}}])
assert len(parity_edges) == 1 and parity_edges[0]['source'] == 'trace_transaction', parity_edges

bundle = build_bundle('bsc', tx_hash, tx, receipt, include_debug=False)
assert bundle['schema'] == 'alpha_trace_bundle.v1', bundle
assert bundle['receipt_summary']['block_number'] == 123, bundle
assert bundle['receipt_summary']['tx_index'] == 5, bundle
assert bundle['transfers'][0]['amount'] == '1000', bundle
assert bundle['calls'] == [], bundle
assert bundle['trace_meta']['debug_requested'] is False, bundle
"""
    trace_bundle_collector_result = subprocess.run(
        [sys.executable, "-c", trace_bundle_collector_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha trace bundle collector guard",
            trace_bundle_collector_result.returncode == 0,
            trace_bundle_collector_result.stderr.strip() or trace_bundle_collector_result.stdout.strip(),
        )
    )

    alpha_swap_sample_review_code = """
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path.cwd()
quote = '0x55d398326f99059ff775485246999027b3197955'
proxy = '0x73d8bd54f7cf5fab43fe4ef40a62d390644946db'
router = '0x6aba0315493b7e6989041c91181337b662fb1b90'
dex_router = '0xb300000b72deaeb607a12d5f54773d1c19c7028d'
user = '0x' + '1' * 40
pool = '0x' + '2' * 40

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    bundle_dir = tmp_path / 'bundles'
    out_dir = tmp_path / 'review'
    bundle_dir.mkdir()
    for idx in range(3):
        token = '0x' + format(idx + 100, '040x')
        payload = {
            'schema': 'alpha_trace_bundle.v1',
            'chain': 'bsc',
            'tx_hash': '0x' + format(idx + 1, '064x'),
            'transaction': {'from': user, 'to': router},
            'receipt_summary': {'from': user, 'to': router, 'status': 1, 'block_number': 100 + idx, 'tx_index': idx},
            'trace_meta': {'debug_traceTransaction': 'error', 'trace_transaction': 'error'},
            'transfers': [
                {'token': token, 'from': proxy, 'to': router, 'amount': '1000'},
                {'token': token, 'from': router, 'to': dex_router, 'amount': '1000'},
                {'token': token, 'from': dex_router, 'to': pool, 'amount': '1000'},
                {'token': quote, 'from': pool, 'to': dex_router, 'amount': '500'},
                {'token': quote, 'from': dex_router, 'to': router, 'amount': '500'},
            ],
        }
        (bundle_dir / f'bundle_{idx}.json').write_text(json.dumps(payload), encoding='utf-8')
    cmd = [
        sys.executable,
        str(root / 'scripts' / 'review_alpha_swap_samples.py'),
        '--bundle-dir',
        str(bundle_dir),
        '--out-dir',
        str(out_dir),
        '--address',
        proxy,
        '--address',
        router,
        '--address',
        dex_router,
    ]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((out_dir / 'latest.json').read_text(encoding='utf-8'))
    assert report['sample_count'] == 3, report
    assert report['distinct_alpha_tokens'] == 3, report
    rows = {row['address']: row for row in report['reviews']}
    assert rows[router]['recommendation'] == 'exchange_aggregator_suspect_candidate', rows[router]
    assert rows[router]['tx_to_distinct_alpha_tokens'] == 3, rows[router]
    assert rows[router]['configured_class'] in {'exchange_aggregator', 'exchange_aggregator_suspect'}, rows[router]
    if rows[router]['configured_class'] == 'exchange_aggregator':
        assert rows[router]['needs_full_trace_before_promotion'] is False, rows[router]
    else:
        assert rows[router]['needs_full_trace_before_promotion'] is True, rows[router]
    assert rows[proxy]['transfer_distinct_alpha_tokens'] == 3, rows[proxy]
    assert rows[dex_router]['configured_class'] == 'dex_router', rows[dex_router]
    assert rows[dex_router]['needs_full_trace_before_promotion'] is False, rows[dex_router]
    assert report['label_proposals'] == [], report['label_proposals']
    assert (out_dir / 'latest.md').exists(), result.stdout

    unknown_router = '0x' + '9' * 40
    proposed = {
        'address': unknown_router,
        'configured_class': '',
        'recommendation': 'exchange_aggregator_suspect_candidate',
        'tx_to_distinct_alpha_tokens': 3,
    }
    from scripts.review_alpha_swap_samples import label_proposal
    proposal = label_proposal(proposed)
    assert proposal['address'] == unknown_router, proposal
    assert proposal['class'] == 'exchange_aggregator_suspect', proposal
"""
    alpha_swap_sample_review_result = subprocess.run(
        [sys.executable, "-c", alpha_swap_sample_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha swap sample batch reviewer",
            alpha_swap_sample_review_result.returncode == 0,
            alpha_swap_sample_review_result.stderr.strip() or alpha_swap_sample_review_result.stdout.strip(),
        )
    )

    alpha_swap_tx_review_code = """
import json
import tempfile
from pathlib import Path

from scripts import review_alpha_swap_txs as module
from scripts.collect_alpha_trace_bundle import tx_hashes_from_args

quote = '0x55d398326f99059ff775485246999027b3197955'
proxy = '0x73d8bd54f7cf5fab43fe4ef40a62d390644946db'
router = '0x6aba0315493b7e6989041c91181337b662fb1b90'
dex_router = '0xb300000b72deaeb607a12d5f54773d1c19c7028d'
pool = '0x' + '2' * 40
user = '0x' + '3' * 40

def topic(address):
    return '0x' + ('0' * 24) + address[2:]

def slot(value):
    return hex(int(value))[2:].rjust(64, '0')

def transfer_log(token, from_addr, to_addr, amount, index):
    return {
        'address': token,
        'topics': [
            '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
            topic(from_addr),
            topic(to_addr),
        ],
        'data': '0x' + slot(amount),
        'logIndex': hex(index),
    }

tx_hashes = ['0x' + format(i + 1, '064x') for i in range(3)]

def fake_rpc_call(chain, method, params):
    tx_hash = params[0]
    idx = tx_hashes.index(tx_hash)
    return {
        'hash': tx_hash,
        'blockNumber': hex(200 + idx),
        'transactionIndex': hex(idx),
        'from': user,
        'to': router,
        'value': '0x0',
        'gas': '0x5208',
        'gasPrice': '0x1',
        'input': '0x',
    }

def fake_receipt(chain, tx_hash):
    idx = tx_hashes.index(tx_hash)
    token = '0x' + format(idx + 500, '040x')
    return {
        'blockNumber': hex(200 + idx),
        'transactionIndex': hex(idx),
        'status': '0x1',
        'from': user,
        'to': router,
        'gasUsed': '0x5208',
        'effectiveGasPrice': '0x1',
        'logs': [
            transfer_log(token, proxy, router, 1000, 0),
            transfer_log(token, router, dex_router, 1000, 1),
            transfer_log(token, dex_router, pool, 1000, 2),
            transfer_log(quote, pool, dex_router, 500, 3),
            transfer_log(quote, dex_router, router, 500, 4),
        ],
    }

module.rpc_call = fake_rpc_call
module.get_transaction_receipt = fake_receipt
with tempfile.TemporaryDirectory() as tmp:
    out_dir = Path(tmp) / 'tx_review'
    tx_file = Path(tmp) / 'external_agent_report.md'
    tx_file.write_text(
        '| token | tx |\\n'
        f'| A | https://bscscan.com/tx/{tx_hashes[0]} |\\n'
        f'| B | `{tx_hashes[1]}` |\\n'
        f'| C | {tx_hashes[1]} duplicate |\\n',
        encoding='utf-8',
    )
    assert tx_hashes_from_args([], tx_file) == tx_hashes[:2]
    written = module.collect_bundles('bsc', tx_hashes, out_dir / 'bundles', include_debug=False)
    review = module.build_review('bsc', written, [proxy, router, dex_router], quote, 3)
    json_path, md_path = module.write_review(review, out_dir / 'review')
    assert json_path.exists() and md_path.exists(), (json_path, md_path)
    assert review['sample_count'] == 3, review
    assert review['distinct_alpha_tokens'] == 3, review
    rows = {row['address']: row for row in review['reviews']}
    assert rows[router]['recommendation'] == 'exchange_aggregator_suspect_candidate', rows[router]
    assert rows[dex_router]['configured_class'] == 'dex_router', rows[dex_router]
    assert rows[dex_router]['needs_full_trace_before_promotion'] is False, rows[dex_router]
"""
    alpha_swap_tx_review_result = subprocess.run(
        [sys.executable, "-c", alpha_swap_tx_review_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "alpha swap tx collect-and-review wrapper",
            alpha_swap_tx_review_result.returncode == 0,
            alpha_swap_tx_review_result.stderr.strip() or alpha_swap_tx_review_result.stdout.strip(),
        )
    )

    symbol_refine_code = """
from pathlib import Path
from scripts.ingest_alpha_signal import parse_signal
from scripts.telegram_signal_collector import refine_symbol_from_chain

text = '''🟩 [BN Alpha] v4 新池子 Initialize
LP / USDT
PoolId: 0x3bca91b9b847cff6f4b666fa1d966981678975e13fd69d647bd11bed99f5fa14
tx: 0xd7c6c7b89917f39eb46f55b8f06b0f5ae892c546d3f2b0dbe116abfd0476ee18'''
parsed = parse_signal(text, Path('/tmp/cap_pool.txt'))
assert parsed['symbol'] in {'', 'UNKNOWN'}, parsed
parsed['chain_enrichment'] = [{
    'status': 'ok',
    'token0': {'symbol': 'USDT'},
    'token1': {'symbol': 'CAP'},
}]
refine_symbol_from_chain(parsed)
assert parsed['symbol'] == 'CAP', parsed
assert parsed['watchlist_proposal']['symbol'] == 'CAP', parsed['watchlist_proposal']
"""
    symbol_refine_result = subprocess.run(
        [sys.executable, "-c", symbol_refine_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("signal parser prefers chain token symbol over LP", symbol_refine_result.returncode == 0, symbol_refine_result.stderr.strip()))

    signal_message_code = """
from scripts.telegram_signal_collector import analysis_message

parsed = {
    'symbol': 'ARX',
    'priority': 'P0_DEEP_REVIEW',
    'title': 'BN Alpha new pool',
    'addresses': [{'address': '0x' + '1' * 40}],
    'txs': ['0x' + '2' * 64],
    'blocks': [123456],
    'pool_ids': ['0x' + '3' * 64],
    'prediction_urls': [],
    'prices': {'pool_price': '0.13'},
    'next_checks': ['official_contract', 'block_transaction_order', 'internal_transactions'],
    'project_registry': {'status': 'updated_project', 'added': ['交易']},
    'chain_enrichment': [
        {
            'status': 'ok',
            'block': 123456,
            'tx_index': 39,
            'token0': {'symbol': 'USDT'},
            'token1': {'symbol': 'ARX'},
            'price_summary': '1 ARX ≈ 0.13 USDT',
            'token_transfers': {'interpretation': '已归档'},
        }
    ],
}
text = analysis_message(parsed, False)
for forbidden in ['0x', 'txIndex', 'block 123456', 'tx_receipt', 'block_transaction_order', 'internal_transactions']:
    assert forbidden not in text, text
assert '有效总结:' in text and '细节已归档' in text and '看开盘块交易顺序' in text and '看贿赂和内部转账' in text, text
print(len(text))
"""
    signal_message_result = subprocess.run(
        [sys.executable, "-c", signal_message_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("signal analysis message hides machine ids", signal_message_result.returncode == 0, signal_message_result.stdout.strip() or signal_message_result.stderr.strip()))

    score_result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sniper_score_local.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(("local scoring script runs", score_result.returncode == 0, score_result.stderr.strip()))

    monitored_ok = False
    monitored_msg = ""
    try:
        monitored = json.loads((ROOT / "config" / "monitored_wallets.json").read_text(encoding="utf-8"))
        wallets = monitored.get("wallets", [])
        quote_tokens = {
            "0x55d398326f99059ff775485246999027b3197955": "USDT",
            "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": "WBNB",
            "0xe9e7cea3dedca5984780bafc599bd69add087d56": "BUSD",
        }
        quote_hits = [
            quote_tokens.get(str(row.get("token_contract", "")).lower(), "")
            for row in wallets
            if str(row.get("token_contract", "")).lower() in quote_tokens
        ]
        front_traced = [
            row for row in wallets
            if "o1_front_buyers_trace" in row.get("sources", [])
        ]
        monitored_ok = len(wallets) >= 32 and len(front_traced) >= 5 and not quote_hits
        monitored_msg = f"{len(wallets)} wallets, {len(front_traced)} front-trace linked, quote token hits={quote_hits}"
    except Exception as exc:
        monitored_msg = str(exc)
    checks.append(("monitored wallet config parses", monitored_ok, monitored_msg))

    snapshot_ok = False
    snapshot_msg = ""
    try:
        snapshot = json.loads((ROOT / "output" / "monitoring" / "latest_snapshot.json").read_text(encoding="utf-8"))
        disabled = set(snapshot.get("disabled_projects", []))
        if "O1" in disabled:
            snapshot_ok = "groups" in snapshot and "alerts" in snapshot and len(snapshot.get("wallets", [])) == 0
        else:
            snapshot_ok = len(snapshot.get("wallets", [])) >= 32 and "groups" in snapshot and "alerts" in snapshot
        snapshot_msg = f"{len(snapshot.get('wallets', []))} wallets, {len(snapshot.get('alerts', []))} alerts, disabled={sorted(disabled)}"
    except Exception as exc:
        snapshot_msg = str(exc)
    checks.append(("latest monitor snapshot parses", snapshot_ok, snapshot_msg))

    project_watch_ok = False
    project_watch_msg = ""
    try:
        project_watch = json.loads((ROOT / "output" / "alpha_project_watch" / "latest.json").read_text(encoding="utf-8"))
        projects = project_watch.get("projects", [])
        skipped = project_watch.get("skipped", [])
        project_watch_ok = (
            len(projects) >= 2
            and "alert_count" in project_watch
            and any(row.get("symbol") == "ARX" and row.get("reason") == "specialized_watch" for row in skipped)
            and all("spot_action" in row.get("analysis", {}) for row in projects)
            and all("perp_action" in row.get("analysis", {}) for row in projects)
        )
        project_watch_msg = f"{len(projects)} projects, alerts={project_watch.get('alert_count')}, skipped={skipped}"
    except Exception as exc:
        project_watch_msg = str(exc)
    checks.append(("alpha project watch parses", project_watch_ok, project_watch_msg))

    alpha_project_dedupe_ok = False
    alpha_project_dedupe_msg = ""
    alpha_project_dedupe_code = """
import importlib.util
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_project_watch', root / 'scripts' / 'alpha_project_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
base_alert = {
    'type': 'BALANCE_CHANGE',
    'symbol': 'CAP',
    'chain': 'bsc',
    'token': 'CAP',
    'token_address': '0x' + '1' * 40,
    'address': '0x' + '2' * 40,
    'role': 'event_distribution',
    'is_quote_balance': False,
    'level': 'HIGH',
}
small_a = dict(base_alert, delta='155738.9162')
small_b = dict(base_alert, delta='142284.6864')
large = dict(base_alert, delta='650000')
assert module.alert_keys([small_a]) == module.alert_keys([small_b]), (module.alert_keys([small_a]), module.alert_keys([small_b]))
assert module.alert_keys([small_a]) != module.alert_keys([large]), (module.alert_keys([small_a]), module.alert_keys([large]))
snapshot_a = {'projects': [{'symbol': 'CAP', 'analysis': {'spot_action': '观察', 'perp_action': '不开仓'}, 'alerts': [small_a]}]}
snapshot_b = {'projects': [{'symbol': 'CAP', 'analysis': {'spot_action': '观察', 'perp_action': '不开仓'}, 'alerts': [small_b]}]}
assert module.project_push_signature(snapshot_a) == module.project_push_signature(snapshot_b), (module.project_push_signature(snapshot_a), module.project_push_signature(snapshot_b))
print(module.alert_keys([small_a])[0])
"""
    alpha_project_dedupe = subprocess.run(
        [sys.executable, "-c", alpha_project_dedupe_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    alpha_project_dedupe_ok = alpha_project_dedupe.returncode == 0
    alpha_project_dedupe_msg = alpha_project_dedupe.stdout.strip() or alpha_project_dedupe.stderr.strip()
    checks.append(("alpha project watch alert dedupe buckets", alpha_project_dedupe_ok, alpha_project_dedupe_msg))

    alpha_opening_ok = False
    alpha_opening_msg = ""
    try:
        alpha_opening = json.loads((ROOT / "output" / "alpha_opening_block_watch" / "latest.json").read_text(encoding="utf-8"))
        events = alpha_opening.get("events", [])
        opened_events = [event for event in events if event.get("status") == "opened"]
        alpha_opening_ok = bool(
            "event_count" in alpha_opening
            and all("spot_action" in event.get("analysis", {}) for event in events)
            and all("perp_action" in event.get("analysis", {}) for event in events)
            and all("direction" in event.get("analysis", {}) for event in events)
            and all("trade_signal" in event.get("analysis", {}) for event in events)
            and all("cohort_status_summary" in event.get("analysis", {}) for event in opened_events)
        )
        alpha_opening_msg = f"events={len(events)}, opened={len(opened_events)}, alerts={alpha_opening.get('alert_count')}"
    except Exception as exc:
        alpha_opening_msg = str(exc)
    checks.append(("generic alpha opening watch parses", alpha_opening_ok, alpha_opening_msg))

    alpha_opening_telegram_ok = False
    alpha_opening_telegram_msg = ""
    alpha_opening_telegram_code = """
import importlib.util
import json
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_opening_block_watch', root / 'scripts' / 'alpha_opening_block_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
snapshot = json.loads((root / 'output' / 'alpha_opening_block_watch' / 'latest.json').read_text(encoding='utf-8'))
text = module.telegram_text(snapshot)
for forbidden in ['0x', 'opening_block', 'scan_to_block']:
    assert forbidden not in text, text
assert len(text) <= 1800, len(text)
if snapshot.get('events'):
    assert '有效总结:' in text and '方向判断:' in text and '买卖信号:' in text and '现货动作:' in text and '合约动作:' in text and '仓位口径:' in text and '细节: 地址、tx、区块已归档' in text, text
else:
    assert '有效总结: 没有开盘窗口项目' in text and '新增告警: 0' in text, text
print(len(text))
"""
    alpha_opening_telegram = subprocess.run(
        [sys.executable, "-c", alpha_opening_telegram_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    alpha_opening_telegram_ok = alpha_opening_telegram.returncode == 0
    alpha_opening_telegram_msg = alpha_opening_telegram.stdout.strip() or alpha_opening_telegram.stderr.strip()
    checks.append(("generic alpha opening Telegram output is concise", alpha_opening_telegram_ok, alpha_opening_telegram_msg))

    alpha_opening_trade_rules_ok = False
    alpha_opening_trade_rules_msg = ""
    alpha_opening_trade_rules_code = """
import importlib.util
import os
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_opening_block_watch', root / 'scripts' / 'alpha_opening_block_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
event = {
    'symbol': 'TEST',
    'quote': {'symbol': 'USDT'},
    'market_context': {
        'snipe_400k_avg_usdt': '0.15',
        'snipe_400k_end_price_usdt': '0.22',
    },
    'initial_price': '0.11',
}
base = {
    'token_bought': '100000',
    'spent_quote': '12000',
    'largest_internal_native': {'amount': '0'},
}
follow = module.analyze_opened(event, [dict(base, buyer_trace={'status': 'held_or_accumulated'})])
project_quote_in = module.analyze_opened(
    {**event, 'liquidity_flow': {'risk': 'project_quote_in', 'summary': '收到 12000 USDT'}},
    [dict(base, buyer_trace={'status': 'held_or_accumulated'})],
)
lp_remove = module.analyze_opened(
    {**event, 'liquidity_flow': {'risk': 'lp_remove', 'summary': 'LP减池/撤流动性 1 次'}},
    [dict(base, buyer_trace={'status': 'held_or_accumulated'})],
)
transfer_unknown = module.analyze_opened(event, [dict(base, buyer_trace={'status': 'mostly_exited_or_transferred'})])
cex_transfer = module.analyze_opened(event, [dict(base, buyer_trace={'status': 'mostly_exited_or_transferred', 'out_destination_classes': 'cex_deposit', 'confirmed_sell_quote_received': '0'})])
sell_confirmed = module.analyze_opened(event, [
    dict(base, buyer_trace={'status': 'mostly_exited_or_transferred', 'confirmed_sell_quote_received': '6000', 'current_balance': '0', 'out_after_buy': '100000'}),
    dict(base, buyer_trace={'status': 'mostly_exited_or_transferred', 'confirmed_sell_quote_received': '6000', 'current_balance': '0', 'out_after_buy': '100000'}),
])
untraced_exit = module.analyze_opened(event, [
    dict(base, buyer_trace={'status': 'mostly_exited_untraced', 'current_balance': '0', 'out_after_buy': '0'}),
])
hot = module.analyze_opened(event, [dict(base, token_bought='1000000', spent_quote='400000', largest_internal_native={'amount': '65'}, buyer_trace={'status': 'held_or_accumulated'})])
old_static_safety = module.inspect_token_contract_safety
module.inspect_token_contract_safety = lambda event: {'status': 'static-ok', 'gate': 'static_check_passed', 'detail': ''}
suspect_buyer_event = {
    **event,
    'chain': 'bsc',
    'token': {'address': '0x' + 'd' * 40, 'decimals': 18},
    'quote': {'address': '0x' + 'e' * 40, 'symbol': 'USDT', 'decimals': 18},
    'market_context': {
        **event['market_context'],
        'mm_or_project_suspect_addresses': ['0x' + '8' * 40],
    },
}
suspect_hold = module.analyze_opened(
    suspect_buyer_event,
    [dict(base, buyer='0x' + '8' * 40, buyer_trace={'status': 'held_or_accumulated'})],
)
alpha_dominant_hold = module.analyze_opened(
    {**event, 'market_context': {**event['market_context'], 'venue_class': 'ALPHA_DOMINANT'}},
    [dict(base, buyer_trace={'status': 'held_or_accumulated'})],
)
module.inspect_token_contract_safety = old_static_safety
assert '可售性未完整验证' in follow['trade_signal'], follow
assert '不跟' in project_quote_in['trade_signal'], project_quote_in
assert project_quote_in['liquidity_flow_risk'] == 'project_quote_in', project_quote_in
assert '卖出/减仓' in lp_remove['trade_signal'], lp_remove
assert lp_remove['liquidity_flow_risk'] == 'lp_remove', lp_remove
assert '不跟' in transfer_unknown['trade_signal'], transfer_unknown
assert '不跟' in cex_transfer['trade_signal'], cex_transfer
assert 'cex_deposit' in cex_transfer['buyer_trace_summary'], cex_transfer
assert cex_transfer['cohort_confirmed_sell_quote'] == '0', cex_transfer
assert '卖出/减仓' in sell_confirmed['trade_signal'], sell_confirmed
assert '不跟' in untraced_exit['trade_signal'], untraced_exit
assert '余额接近0' in untraced_exit['buyer_trace_summary'], untraced_exit
assert untraced_exit['cohort_net_out_pct'] == '100', untraced_exit
assert '不追' in hot['trade_signal'], hot
assert '偏多' not in suspect_hold['direction'], suspect_hold
assert '聪明钱承接' in suspect_hold['conclusion'], suspect_hold
assert suspect_hold['buyer_caution_reason'] == '买家为项目/MM/聚合器嫌疑地址', suspect_hold
assert '偏多' not in alpha_dominant_hold['direction'], alpha_dominant_hold
assert alpha_dominant_hold['onchain_netflow_reliable'] == 'False', alpha_dominant_hold
assert 'Alpha主导净流未认证' in alpha_dominant_hold['buyer_caution_reason'], alpha_dominant_hold
assert sell_confirmed['cohort_confirmed_sell_quote'] == '12000', sell_confirmed
assert sell_confirmed['total_spent_quote'] == '24000', sell_confirmed
assert sell_confirmed['current_cohort_quote_est'] == '0', sell_confirmed
assert sell_confirmed['cohort_net_out_pct'] == '100', sell_confirmed
assert '首批历史开盘买入 24000.0000 USDT（非当前持仓）' in sell_confirmed['cohort_status_summary'], sell_confirmed
assert '按首批成本约 0 USDT' in sell_confirmed['cohort_status_summary'], sell_confirmed
assert '当前仍在原买入钱包' in sell_confirmed['cohort_status_summary'], sell_confirmed
opened_event = {
    **event,
    'status': 'opened',
    'opening_block': 123,
    'analysis': {**hot, 'buyer_trace_summary': '已追踪2个首批买家；截至区块999'},
    'rows': [dict(base, tx='0xabc', buyer='0x' + '1' * 40, buyer_trace={'status': 'held_or_accumulated', 'out_after_buy': '0'})],
}
keys = module.event_alert_keys(opened_event)
assert not any('截至区块' in key for key in keys), keys
trade_key = next(key for key in keys if key.startswith('trade_signal|TEST|'))
legacy_seen = {'trade_signal|TEST|' + hot['trade_signal'] + '|已追踪2个首批买家；截至区块998'}
assert module.alert_key_seen(trade_key, legacy_seen), trade_key
classified_event = {
    'symbol': 'TEST',
    'chain': 'bsc',
    'token': {'address': '0x' + 'd' * 40, 'decimals': 18},
    'quote': {'address': '0x' + 'e' * 40, 'symbol': 'USDT', 'decimals': 18},
    'market_context': {
        'cex_deposit_addresses': ['0x' + 'c' * 40],
        'cex_hot_wallet_addresses': ['0x' + '4' * 40],
        'exchange_rebalance_addresses': ['0x' + '7' * 40],
        'mm_or_project_suspect_addresses': ['0x' + '8' * 40],
        'bridge_addresses': ['0x' + '2' * 40],
        'neutral_contracts': [{'address': '0x' + 'f' * 40}],
        'locker_addresses': [{'address': '0x' + '3' * 40}],
    },
}
assert module.destination_class(classified_event, '0x' + 'c' * 40) == 'cex_deposit'
assert module.destination_class(classified_event, '0x' + '4' * 40) == 'cex_deposit'
assert module.destination_class(classified_event, '0x' + '7' * 40) == 'exchange_rebalance'
assert module.destination_class(classified_event, '0x' + '8' * 40) == 'mm_or_project_suspect'
assert module.destination_class(classified_event, '0x' + '2' * 40) == 'bridge'
assert module.destination_class(classified_event, '0x' + '3' * 40) == 'lp_locker_or_staking'
assert module.destination_class(classified_event, '0x' + 'f' * 40) == 'lp_locker_or_staking'
assert module.destination_class(classified_event, '0x46a15b0b27311cedf172ab29e4f4766fbe7f4364') == 'lp_locker_or_staking'
assert module.destination_class(classified_event, '0x1b81d678ffb9c0263b24a97847620c99d213eb14') == 'dex_router'
assert '0x238a358808379702088667322f80ac48bad5e6c4' in module.excluded_addresses(classified_event)
known_est_event = {**classified_event, 'known_txs': [{'tx': '0x' + 'a' * 64, 'estimated_spent_quote': '400200'}]}
assert module.known_tx_estimated_spent_quote(known_est_event, '0x' + 'a' * 64) == module.Decimal('400200')
known_est_analysis = module.analyze_opened(
    event,
    [dict(base, spent_quote='0', estimated_spent_quote='400200', buyer_trace={'status': 'held_or_accumulated'})],
)
assert known_est_analysis['total_spent_quote'] == '400200', known_est_analysis
old_has_contract_code = module.has_contract_code
module.has_contract_code = lambda chain, address: address == '0x' + '5' * 40
assert module.destination_class(classified_event, '0x' + '5' * 40) == 'unknown_contract_pending_bearish'
module.has_contract_code = old_has_contract_code
assert module.trace_start_block(100, 105, 50, 0, False) == 100
assert module.trace_start_block(100, 1000, 50, 0, False) == 950
assert module.trace_start_block(100, 1000, 50, 1200, True) == 100
assert module.trace_start_block(100, 2000, 50, 1200, True) == 1950
module.CONTRACT_SAFETY_CACHE.clear()
module.contract_code = lambda chain, address: '0x' + module.OWNER_SELECTORS['owner'][2:] + module.BOOL_RISK_SELECTORS['paused'][2:]

def fake_static_call(chain, address, selector):
    if selector == module.OWNER_SELECTORS['owner']:
        return '0x' + ('0' * 24) + ('1' * 40)
    if selector == module.BOOL_RISK_SELECTORS['paused']:
        return '0x' + '0' * 64
    return '0x'

module.optional_eth_call = fake_static_call
contract_warning = module.inspect_token_contract_safety(classified_event)
assert contract_warning['gate'] == 'blocked_contract_controls_unverified', contract_warning

def fake_paused_call(chain, address, selector):
    if selector == module.BOOL_RISK_SELECTORS['paused']:
        return '0x' + '0' * 63 + '1'
    return '0x'

module.CONTRACT_SAFETY_CACHE.clear()
module.optional_eth_call = fake_paused_call
contract_blocked = module.inspect_token_contract_safety(classified_event)
assert contract_blocked['gate'] == 'blocked_static_contract_risk', contract_blocked
assert module.alert_amount_bucket(module.Decimal('19999.99'), module.Decimal('10000')) == '10000'
new_trace_key = 'trace|TEST|0x' + ('1' * 40) + '|partially_moved|eoa_or_unlabeled|10000'
old_trace_key = 'trace|TEST|0x' + ('1' * 40) + '|partially_moved|eoa_or_unlabeled|0'
assert module.alert_key_seen(new_trace_key, {old_trace_key}), new_trace_key

def slot(value):
    return hex(int(value) % (2 ** 256))[2:].rjust(64, '0')

lp_log = {
    'address': '0x46a15b0b27311cedf172ab29e4f4766fbe7f4364',
    'topics': [module.DECREASE_LIQUIDITY_TOPIC, '0x' + '0' * 63 + '1'],
    'data': '0x' + slot(100) + slot(200) + slot(300),
    'transactionHash': '0xlp',
    'blockNumber': '0x1',
    'logIndex': '0x0',
}
lp_row = module.liquidity_event_row(lp_log, {'label': 'position manager', 'role': 'lp_position_manager'})
assert lp_row['event'] == 'DecreaseLiquidity' and lp_row['direction'] == 'remove', lp_row

buyer = '0x' + 'a' * 40
recipient = '0x' + 'b' * 40
router = '0x' + '9' * 40

def make_log(address, from_addr, to_addr, amount, tx='0xnext', block=12, idx=1):
    return {
        'address': address,
        'topics': [module.TRANSFER_TOPIC, module.address_topic(from_addr), module.address_topic(to_addr)],
        'data': hex(int(module.Decimal(str(amount)) * (module.Decimal(10) ** 18))),
        'transactionHash': tx,
        'blockNumber': hex(block),
        'logIndex': hex(idx),
    }

module.has_contract_code = lambda chain, address: False
module.get_logs_quick = lambda *args, **kwargs: [make_log(classified_event['token']['address'], recipient, router, '1000')]

def fake_quick_rpc_call(chain, method, params, timeout):
    tx_hash = params[0]
    if tx_hash == '0xnext':
        return {'logs': [make_log(classified_event['quote']['address'], router, recipient, '500', tx='0xnext', block=12, idx=2)]}
    return {'logs': []}

module.quick_rpc_call = fake_quick_rpc_call
classified = module.classify_outgoing_tx(
    classified_event,
    buyer,
    '0xorig',
    [{'to': recipient, 'block': 11, 'tx': '0xorig', 'log_index': 1, 'amount': module.Decimal('1000')}],
    20,
)
assert classified['quote_received'] == module.Decimal('500'), classified
assert 'next_hop_dex_sell_to_quote' in classified['classes'], classified
def fake_transfer_ok(chain, method, params, timeout):
    return '0x' + '0' * 63 + '1'

module.quick_rpc_call = fake_transfer_ok
safe = module.simulate_transfer_safety(classified_event, buyer, module.Decimal('10'))
assert safe['status'] == 'transfer_verified', safe
quote_payload = module.encode_quoter_v3_exact_input_single(classified_event['token']['address'], classified_event['quote']['address'], 10 ** 18, 100)
assert quote_payload.startswith(module.QUOTE_EXACT_INPUT_SINGLE_SELECTOR), quote_payload

def fake_transfer_blocked(chain, method, params, timeout):
    raise RuntimeError('execution reverted')

module.quick_rpc_call = fake_transfer_blocked
blocked = module.simulate_transfer_safety(classified_event, buyer, module.Decimal('10'))
assert blocked['status'] == 'blocked', blocked

def fake_quote_ok(chain, method, params, timeout):
    return '0x' + hex(123 * 10 ** 18)[2:].rjust(64, '0') + '0' * 64 * 3

module.quick_rpc_call = fake_quote_ok
quote_ok = module.simulate_dex_quote_safety(classified_event, module.Decimal('10'))
assert quote_ok['status'] == 'dex_quote_verified', quote_ok
combined_safety = module.sell_safety_summary([
    {'buyer_trace': {'transfer_safety_status': 'transfer_verified', 'transfer_safety_detail': 'probe_amount=1', 'dex_quote_status': 'dex_quote_verified', 'dex_quote_detail': 'fee=100'}}
])
assert combined_safety['gate'] == 'blocked_tax_unverified', combined_safety
infinity_event = {
    **classified_event,
    'pool_id': '0x' + '2' * 64,
    'hook': module.ZERO,
    'fee': '100',
    'parameters': '0x' + '0' * 64,
}
pool_key = module.infinity_pool_key(infinity_event)
assert pool_key['status'] == 'ok' and pool_key['zero_for_one'] is True, pool_key
infinity_payload = module.encode_infinity_cl_quote_exact_input_single(pool_key, 10 ** 18)
assert infinity_payload.startswith(module.PANCAKE_INFINITY_CL_QUOTE_EXACT_INPUT_SINGLE_SELECTOR), infinity_payload
assert len(infinity_payload) == 2 + 8 + 64 * 11, len(infinity_payload)
old_infinity_router_probe = os.environ.pop('ALPHA_OPENING_INFINITY_ROUTER_SELL_PROBE', None)
try:
    infinity_router_skip = module.simulate_router_sell_safety(infinity_event, buyer, module.Decimal('10'))
    assert infinity_router_skip['status'] == 'unverified' and 'infinity_router' in infinity_router_skip['detail'], infinity_router_skip
finally:
    if old_infinity_router_probe is not None:
        os.environ['ALPHA_OPENING_INFINITY_ROUTER_SELL_PROBE'] = old_infinity_router_probe

def fake_infinity_quote(chain, method, params, timeout):
    assert params[0]['to'] == module.PANCAKE_INFINITY_CL_QUOTER, params
    assert params[0]['data'].startswith(module.PANCAKE_INFINITY_CL_QUOTE_EXACT_INPUT_SINGLE_SELECTOR), params
    return '0x' + hex(321 * 10 ** 18)[2:].rjust(64, '0') + hex(999)[2:].rjust(64, '0')

module.quick_rpc_call = fake_infinity_quote
infinity_quote_ok = module.simulate_infinity_cl_quote_safety(infinity_event, module.Decimal('10'))
assert infinity_quote_ok['status'] == 'infinity_cl_quote_verified', infinity_quote_ok
combined_infinity_safety = module.sell_safety_summary([
    {'buyer_trace': {'transfer_safety_status': 'transfer_verified', 'dex_quote_status': 'infinity_cl_quote_verified', 'dex_quote_detail': infinity_quote_ok['detail']}}
])
assert combined_infinity_safety['gate'] == 'blocked_tax_unverified', combined_infinity_safety
assert 'Quoter不触发税费' in combined_infinity_safety['status'], combined_infinity_safety
combined_infinity_roundtrip_safety = module.sell_safety_summary([
    {
        'buyer_trace': {
            'transfer_safety_status': 'transfer_verified',
            'dex_quote_status': 'infinity_cl_quote_verified',
            'router_sell_status': 'infinity_roundtrip_eth_call_success_no_recovery_rate',
            'router_sell_detail': 'v4往返eth_call未revert: recovery_rate_unavailable',
        }
    }
])
assert combined_infinity_roundtrip_safety['gate'] == 'blocked_infinity_recovery_unverified', combined_infinity_roundtrip_safety
assert '回收率未验证' in combined_infinity_roundtrip_safety['status'], combined_infinity_roundtrip_safety
assert '执行门通过' not in combined_infinity_roundtrip_safety['status'], combined_infinity_roundtrip_safety
combined_infinity_low_recovery = module.sell_safety_summary([
    {
        'buyer_trace': {
            'transfer_safety_status': 'transfer_verified',
            'dex_quote_status': 'infinity_cl_quote_verified',
            'router_sell_status': 'infinity_roundtrip_low_recovery',
            'router_sell_detail': 'v4往返回收率≈50%',
        }
    }
])
assert combined_infinity_low_recovery['gate'] == 'blocked_infinity_low_recovery', combined_infinity_low_recovery
combined_infinity_recovery_verified = module.sell_safety_summary([
    {
        'buyer_trace': {
            'transfer_safety_status': 'transfer_verified',
            'dex_quote_status': 'infinity_cl_quote_verified',
            'router_sell_status': 'infinity_roundtrip_recovery_verified',
            'router_sell_detail': 'v4往返回收率≈99%',
        }
    }
])
assert combined_infinity_recovery_verified['gate'] == 'infinity_recovery_rate_verified_tax_uncertain', combined_infinity_recovery_verified
legacy_infinity_roundtrip_safety = module.sell_safety_summary([
    {
        'buyer_trace': {
            'transfer_safety_status': 'transfer_verified',
            'dex_quote_status': 'infinity_cl_quote_verified',
            'router_sell_status': 'infinity_roundtrip_eth_call_verified',
            'router_sell_detail': 'legacy status',
        }
    }
])
assert legacy_infinity_roundtrip_safety['gate'] == 'blocked_infinity_recovery_unverified', legacy_infinity_roundtrip_safety

def fake_quote_fail(chain, method, params, timeout):
    raise RuntimeError('execution reverted')

module.quick_rpc_call = fake_quote_fail
quote_failed = module.simulate_dex_quote_safety(classified_event, module.Decimal('10'))
assert quote_failed['status'] == 'quote_failed', quote_failed

module.BALANCE_SLOT_CACHE.clear()
module.ALLOWANCE_SLOT_CACHE.clear()
module.web3_keccak_word = lambda chain, raw_hex: '0x' + (raw_hex[-64:] if len(raw_hex) >= 64 else raw_hex.rjust(64, '0'))
module.raw_balance_of = lambda chain, token, holder: 10 ** 18
balance_key = module.mapping_storage_key(classified_event['chain'], buyer, 3)
module.storage_at = lambda chain, contract, key: hex(10 ** 18) if key == balance_key else '0x0'

def fake_router_sell(chain, method, params, timeout):
    if method == 'eth_call' and len(params) == 3 and params[0].get('to') == classified_event['token']['address']:
        data = params[0].get('data', '')
        if data.startswith('0x70a08231'):
            return '0x' + hex(10 ** 18)[2:].rjust(64, '0')
        if data.startswith('0xdd62ed3e'):
            return '0x' + ('f' * 64)
    if method == 'eth_call' and len(params) == 3 and params[0].get('to') == module.PANCAKE_V3_ROUTER:
        override = params[2]
        state_diff = override[classified_event['token']['address']]['stateDiff']
        assert state_diff, override
        return '0x' + hex(456 * 10 ** 18)[2:].rjust(64, '0')
    return '0x'

module.quick_rpc_call = fake_router_sell
router_ok = module.simulate_router_sell_safety(classified_event, buyer, module.Decimal('10'))
assert router_ok['status'] == 'router_sell_verified', router_ok
combined_router_safety = module.sell_safety_summary([
    {'buyer_trace': {'transfer_safety_status': 'transfer_verified', 'dex_quote_status': 'dex_quote_verified', 'router_sell_status': 'router_sell_verified', 'router_sell_detail': 'router ok'}}
])
assert combined_router_safety['gate'] == 'router_sell_verified_tax_uncertain', combined_router_safety
assert '可售性' in module.telegram_text({'events': [{'symbol': 'TEST', 'priority': 'P0', 'analysis': follow}]}), follow
print(follow['trade_signal'] + ' / ' + transfer_unknown['trade_signal'] + ' / ' + sell_confirmed['trade_signal'] + ' / ' + hot['trade_signal'])
"""
    alpha_opening_trade_rules = subprocess.run(
        [sys.executable, "-c", alpha_opening_trade_rules_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    alpha_opening_trade_rules_ok = alpha_opening_trade_rules.returncode == 0
    alpha_opening_trade_rules_msg = alpha_opening_trade_rules.stdout.strip() or alpha_opening_trade_rules.stderr.strip()
    checks.append(("generic alpha opening trade rules", alpha_opening_trade_rules_ok, alpha_opening_trade_rules_msg))

    arx_ok = False
    arx_msg = ""
    try:
        arx = json.loads((ROOT / "output" / "arx_launch_watch" / "latest.json").read_text(encoding="utf-8"))
        analysis = arx.get("analysis", {})
        arx_ok = bool(
            arx.get("latest_block")
            and "spot_action" in analysis
            and "perp_action" in analysis
            and "attention" in analysis
            and "suppressed_small_event_transfers" in arx
        )
        arx_msg = f"alerts={len(arx.get('alerts', []))}, suppressed={arx.get('suppressed_small_event_transfers')}, spot={analysis.get('spot_action', '')}"
    except Exception as exc:
        arx_msg = str(exc)
    checks.append(("ARX launch watch action fields present", arx_ok, arx_msg))

    arx_opening_ok = False
    arx_opening_msg = ""
    try:
        arx_opening = json.loads((ROOT / "output" / "arx_opening_block_watch" / "latest.json").read_text(encoding="utf-8"))
        analysis = arx_opening.get("analysis", {})
        arx_opening_ok = bool(
            arx_opening.get("generated_at")
            and "spot_action" in analysis
            and "perp_action" in analysis
            and "operator_behavior" in analysis
            and "total_spent_usdt" in analysis
            and "direction" in analysis
            and "trade_signal" in analysis
            and "buyer_trace_summary" in analysis
            and "cohort_status_summary" in analysis
            and "current_cohort_arx" in analysis
            and "cohort_net_out_pct" in analysis
            and "cohort_confirmed_sell_usdt" in analysis
            and arx_opening.get("status") in {"waiting", "opened"}
        )
        arx_opening_msg = f"status={arx_opening.get('status')}, opening_block={arx_opening.get('opening_block')}, spent={analysis.get('total_spent_usdt')}, txs={arx_opening.get('relevant_tx_count', 0)}, trace={analysis.get('buyer_trace_summary')}"
    except Exception as exc:
        arx_opening_msg = str(exc)
    checks.append(("ARX opening block watch parses", arx_opening_ok, arx_opening_msg))

    arx_telegram_ok = False
    arx_telegram_msg = ""
    telegram_preview_code = """
import importlib.util
import json
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('arx_opening_block_watch', root / 'scripts' / 'arx_opening_block_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
snapshot = json.loads((root / 'output' / 'arx_opening_block_watch' / 'latest.json').read_text(encoding='utf-8'))
text = module.telegram_text(snapshot)
for forbidden in ['0x', 'opening_block', 'scan_to_block', 'buyer ']:
    assert forbidden not in text, text
assert len(text) <= 1500, len(text)
assert '有效总结:' in text and '动作信号:' in text and '仓位口径:' in text and '买后去向:' in text and '现货动作:' in text and '合约动作:' in text and '细节: 地址、tx、区块已归档' in text, text
old_key = 'buyer_trace|0xabc|mostly_exited_untraced|100|0|eoa_or_unlabeled|1'
new_key = 'buyer_trace|0xabc|mostly_exited_untraced|100|0|eoa_or_unlabeled|2'
assert module.alert_key_seen(new_key, {old_key}), new_key
assert any(key.startswith('trade_signal|ARX|') for key in module.alert_keys(snapshot)), module.alert_keys(snapshot)
print(len(text))
"""
    telegram_preview = subprocess.run(
        [sys.executable, "-c", telegram_preview_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    arx_telegram_ok = telegram_preview.returncode == 0
    arx_telegram_msg = telegram_preview.stdout.strip() or telegram_preview.stderr.strip()
    checks.append(("ARX Telegram output is concise", arx_telegram_ok, arx_telegram_msg))

    arx_launch_telegram_ok = False
    arx_launch_telegram_msg = ""
    arx_launch_telegram_code = """
import importlib.util
import json
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('arx_launch_watch', root / 'scripts' / 'arx_launch_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
snapshot = json.loads((root / 'output' / 'arx_launch_watch' / 'latest.json').read_text(encoding='utf-8'))
text = module.telegram_text(snapshot)
for forbidden in ['0x', 'tx:', 'block', '区块', '重点余额']:
    assert forbidden not in text, text
assert len(text) <= 1800, len(text)
assert '有效总结:' in text and '现货动作:' in text and '合约动作:' in text and '新增告警:' in text, text
assert '首批狙击强度已确认' not in text, text
assert ('首批历史' in text or '当前去向' in text), text
print(len(text))
"""
    arx_launch_telegram = subprocess.run(
        [sys.executable, "-c", arx_launch_telegram_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    arx_launch_telegram_ok = arx_launch_telegram.returncode == 0
    arx_launch_telegram_msg = arx_launch_telegram.stdout.strip() or arx_launch_telegram.stderr.strip()
    checks.append(("ARX launch Telegram output is concise", arx_launch_telegram_ok, arx_launch_telegram_msg))

    prediction_ok = False
    prediction_msg = ""
    try:
        prediction = json.loads((ROOT / "output" / "prediction_markets" / "latest_prediction_markets.json").read_text(encoding="utf-8"))
        prediction_ok = "rows" in prediction and "item_count" in prediction
        prediction_msg = f"{prediction.get('item_count', 0)} items, {len(prediction.get('rows', []))} rows"
    except Exception as exc:
        prediction_msg = str(exc)
    checks.append(("prediction market snapshot parses", prediction_ok, prediction_msg))

    perp_snapshot_ok = False
    perp_snapshot_msg = ""
    try:
        perp_snapshot = json.loads((ROOT / "output" / "perp_oi_funding_watch" / "latest.json").read_text(encoding="utf-8"))
        rows = perp_snapshot.get("rows", [])
        perp_snapshot_ok = "rows" in perp_snapshot and "alert_count" in perp_snapshot and isinstance(rows, list)
        perp_snapshot_msg = f"{perp_snapshot.get('item_count', 0)} items, {len(rows)} rows, alerts={perp_snapshot.get('alert_count', 0)}"
    except Exception as exc:
        perp_snapshot_msg = str(exc)
    checks.append(("perp OI/funding snapshot parses", perp_snapshot_ok, perp_snapshot_msg))

    surf_aux_snapshot_ok = False
    surf_aux_snapshot_msg = ""
    try:
        surf_aux_snapshot = json.loads((ROOT / "output" / "surf_aux_market_watch" / "latest.json").read_text(encoding="utf-8"))
        rows = surf_aux_snapshot.get("rows", [])
        surf_aux_snapshot_ok = (
            surf_aux_snapshot.get("schema") == "surf_aux_market_watch.v1"
            and surf_aux_snapshot.get("authority") == "auxiliary_context_only"
            and isinstance(rows, list)
            and all("summary" in row for row in rows)
        )
        surf_aux_snapshot_msg = f"{surf_aux_snapshot.get('row_count', 0)} rows, credits={surf_aux_snapshot.get('credits_used_observed', 0)}"
    except Exception as exc:
        surf_aux_snapshot_msg = str(exc)
    checks.append(("Surf auxiliary market snapshot parses", surf_aux_snapshot_ok, surf_aux_snapshot_msg))

    external_aux_snapshot_ok = False
    external_aux_snapshot_msg = ""
    try:
        external_aux_snapshot = json.loads((ROOT / "output" / "external_aux_sources" / "latest.json").read_text(encoding="utf-8"))
        rows = external_aux_snapshot.get("rows", [])
        external_aux_snapshot_ok = (
            external_aux_snapshot.get("schema") == "external_aux_source_readiness.v1"
            and isinstance(rows, list)
            and all("status" in row and "authority" in row for row in rows)
        )
        external_aux_snapshot_msg = (
            f"{external_aux_snapshot.get('source_count', 0)} sources, "
            f"needs_credentials={external_aux_snapshot.get('needs_credentials_count', 0)}, "
            f"validated={external_aux_snapshot.get('validated_count', 0)}"
        )
    except Exception as exc:
        external_aux_snapshot_msg = str(exc)
    checks.append(("external auxiliary source snapshot parses", external_aux_snapshot_ok, external_aux_snapshot_msg))

    alpha_price_perp_text_ok = False
    alpha_price_perp_text_msg = ""
    alpha_price_perp_text_code = """
import importlib.util
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_price_momentum_watch', root / 'scripts' / 'alpha_price_momentum_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
perp_context = {
    'snapshot_status': 'ok',
    'status': 'ok',
    'perp_symbol': 'CAPUSDT',
    'perp_state': 'active_perp_market',
    'direction_hint': '可观察',
    'open_interest_usd': '3370000',
    'last_funding_rate': '0.0001',
    'quote_volume_24h': '75300000',
    'oi_usd_delta_pct': '12',
    'mark_price_delta_pct': '6',
    'trend_status': 'ok',
    'trend_hint': '多头增量',
    'trend_action': 'OI扩张且价格上涨，重点等现货承接和链上净流确认',
    'baseline_age_minutes': '60',
    'action': '合约成交活跃，可配合链上出流和价格结构判断',
}
snapshot = {
    'events': [{
        'symbol': 'CAP',
        'priority': 'P1',
        'analysis': {
            'direction': '观察偏多',
            'trade_signal': 'Alpha 收盘价放量走强；等待链上确认',
            'spot_action': '小仓只等回踩，不追市价',
            'perp_action': module.perp_action_summary(perp_context),
            'window_15m': {'open': '0.01', 'high': '0.04', 'low': '0.009', 'close': '0.03', 'quote_volume': '300000'},
            'depth': {'ask_5pct_usdt': '120000', 'bid_5pct_usdt': '90000'},
            'venue': {'venue_class': 'ALPHA_DOMINANT', 'coverage': 'ONCHAIN_NETFLOW_UNRELIABLE'},
            'perp_context': perp_context,
        },
    }]
}
text = module.telegram_text(snapshot)
assert '合约层:' in text and 'CAPUSDT' in text and 'OI≈' in text, text
assert '60m OI' in text and '多头增量' in text, text
summary_idx = text.rfind('项目总结汇总:')
assert summary_idx > text.find('合约层:'), text
assert text.count('项目总结汇总:') == 1, text
assert '现货: 小仓只等回踩，不追市价' in text and '合约: 偏多观察' in text, text
quiet_price_event = {
    'symbol': 'CAP',
    'analysis': {
        'direction': '观察',
        'trade_signal': '无价格异动',
        'perp_action': module.perp_action_summary(perp_context),
        'window_15m': {'high_pct': '1', 'close_pct': '1', 'quote_volume': '1000'},
        'perp_context': perp_context,
    },
}
quiet_keys = module.event_alert_keys(quiet_price_event)
assert quiet_keys and quiet_keys[0].startswith('perp_trend|CAP|多头增量'), quiet_keys
quiet_price_event_later = {
    'symbol': 'CAP',
    'analysis': {
        'direction': '观察',
        'trade_signal': '无价格异动',
        'perp_action': module.perp_action_summary({**perp_context, 'baseline_age_minutes': '65'}),
        'window_15m': {'high_pct': '1', 'close_pct': '1', 'quote_volume': '1000'},
        'perp_context': {**perp_context, 'baseline_age_minutes': '65'},
    },
}
assert module.event_alert_keys(quiet_price_event_later) == quiet_keys, (module.event_alert_keys(quiet_price_event_later), quiet_keys)
down_price_event = {
    'symbol': 'LAB',
    'analysis': {
        'direction': '放量走弱',
        'trade_signal': 'Alpha 放量收跌；卖出/减仓观察',
        'window_15m': {'high_pct': '1', 'low_pct': '-18', 'close_pct': '-9', 'quote_volume': '300000', 'from_utc8': '2026-07-02 15:31', 'to_utc8': '2026-07-02 15:45'},
        'perp_context': {},
    },
}
down_keys = module.event_alert_keys(down_price_event)
assert down_keys and down_keys[0].startswith('alpha_price|LAB|放量走弱'), down_keys
legacy_down_key = 'alpha_price|LAB|放量走弱|0|15|0|300000|2026-07-02 15:31|2026-07-02 15:45'
assert module.unseen_alert_keys(module.event_alert_key_pairs(down_price_event), {legacy_down_key}) == [], module.event_alert_key_pairs(down_price_event)
down_price_event_later = {
    'symbol': 'LAB',
    'analysis': {
        'direction': '放量走弱',
        'trade_signal': 'Alpha 放量收跌；卖出/减仓观察',
        'window_15m': {'high_pct': '1', 'low_pct': '-18', 'close_pct': '-9', 'quote_volume': '300000', 'from_utc8': '2026-07-02 15:36', 'to_utc8': '2026-07-02 15:50'},
        'perp_context': {},
    },
}
assert module.event_alert_keys(down_price_event_later) == down_keys, (module.event_alert_keys(down_price_event_later), down_keys)
assert '2026-07-02 15:45' not in down_keys[0], down_keys
crossed = module.depth_stats({'bids': [['1.2', '10']], 'asks': [['1.0', '10']]}, module.Decimal('1.1'))
assert crossed.get('orderbook_status') == 'crossed_or_stale', crossed
assert '盘口结构不下方向' in ''.join(crossed.get('microstructure_notes') or []), crossed
assert module.depth_amounts_reliable(crossed) is False, crossed
crossed_text = module.telegram_text({'events': [{
    'symbol': 'CROSS',
    'priority': 'P0',
    'analysis': {
        'direction': '观察',
        'trade_signal': '无价格异动',
        'spot_action': '观察',
        'perp_action': '不开仓',
        'window_15m': {'open': '1', 'high': '1', 'low': '1', 'close': '1', 'quote_volume': '1'},
        'depth': crossed,
        'venue': {},
        'perp_context': {},
        'reason': '盘口结构: 盘口交叉或快照异常，盘口结构不下方向',
    },
}]})
assert '深度金额不采用' in crossed_text and '+5%卖盘≈' not in crossed_text, crossed_text
normal_depth = module.depth_stats({'bids': [['0.9', '10']], 'asks': [['1.0', '10']]}, module.Decimal('0.95'))
assert module.depth_amounts_reliable(normal_depth) is True, normal_depth
assert len(text) <= 2200, len(text)
print(len(text))
"""
    alpha_price_perp_text = subprocess.run(
        [sys.executable, "-c", alpha_price_perp_text_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    alpha_price_perp_text_ok = alpha_price_perp_text.returncode == 0
    alpha_price_perp_text_msg = alpha_price_perp_text.stdout.strip() or alpha_price_perp_text.stderr.strip()
    checks.append(("alpha price Telegram includes perp layer", alpha_price_perp_text_ok, alpha_price_perp_text_msg))

    prelaunch_watch_code = """
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('alpha_prelaunch_watch', root / 'scripts' / 'alpha_prelaunch_watch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
config = {
    'items': [
        {
            'symbol': 'WDATAIP',
            'priority': 'P0_DEEP_REVIEW',
            'chain': 'bsc',
            'contracts': [{'chain': 'bsc', 'address': '0xa37eded373c5cdf88644db7c6b89f222e756afb2'}],
            'known_times': [{'time': '2026-07-02 16:00'}],
            'facts': {'display_symbol': 'DATA', 'raw_symbol': 'WDATAIP', 'project_name': 'Data Network'},
            'required_checks': ['official_contract', 'holder_distribution'],
        }
    ]
}
events = module.build_events(config, datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc))
assert len(events) == 1, events
assert events[0]['phase'] == 'T_MINUS_24H', events
assert events[0]['display_name'] == 'DATA/WDATAIP · Data Network', events
assert '未见真实加池' in module.phase_action('T_MINUS_2H')
print(events[0]['display_name'])
"""
    prelaunch_watch = subprocess.run(
        [sys.executable, "-c", prelaunch_watch_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    prelaunch_watch_ok = prelaunch_watch.returncode == 0
    prelaunch_watch_msg = prelaunch_watch.stdout.strip() or prelaunch_watch.stderr.strip()
    checks.append(("alpha prelaunch watch identifies upcoming launch window", prelaunch_watch_ok, prelaunch_watch_msg))

    daily_perp_section_ok = False
    daily_perp_section_msg = ""
    daily_perp_section_code = """
import importlib.util
from pathlib import Path

root = Path.cwd()
spec = importlib.util.spec_from_file_location('build_alpha_daily_report', root / 'scripts' / 'build_alpha_daily_report.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
text = module.build_report()
assert '## Perp / OI / Funding' in text, text
assert '## Alpha Price Momentum' in text, text
assert '## Holder Concentration' in text, text
assert '## Surf Auxiliary Market' in text, text
assert '## External Auxiliary Sources' in text, text
assert '## Prelaunch Schedule' in text, text
assert '15m high/low/close' in text and 'Book' in text and 'Alpha 价格层' in text, text
assert '排除托管后前十' in text or 'No holder concentration snapshot available.' in text, text
assert '外部全量Top10' in text or 'No holder concentration snapshot available.' in text, text
assert '联动判断' in text or 'No holder concentration snapshot available.' in text, text
assert 'Action Queue' in text, text
print(len(text))
"""
    daily_perp_section = subprocess.run(
        [sys.executable, "-c", daily_perp_section_code],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    daily_perp_section_ok = daily_perp_section.returncode == 0
    daily_perp_section_msg = daily_perp_section.stdout.strip() or daily_perp_section.stderr.strip()
    checks.append(("daily report includes market and holder auxiliary sections", daily_perp_section_ok, daily_perp_section_msg))

    csv_path = ROOT / "output" / "sniper_engine" / "signal_scores.csv"
    rows: list[dict[str, str]] = []
    if csv_path.exists():
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    checks.append(("score CSV has rows", len(rows) > 0, f"{len(rows)} rows"))

    lane_counts: dict[str, int] = {}
    for row in rows:
        lane_counts[row.get("lane", "")] = lane_counts.get(row.get("lane", ""), 0) + 1
    checks.append(("P0 queue present", lane_counts.get("P0_DEEP_REVIEW", 0) > 0, str(lane_counts)))

    o1_rows = [row for row in rows if "2067399680217198964" in row.get("tweet_url", "")]
    o1_ok = bool(o1_rows and o1_rows[0].get("lane") == "P0_DEEP_REVIEW")
    o1_msg = ""
    if o1_rows:
        o1_msg = f"score={o1_rows[0].get('score')} lane={o1_rows[0].get('lane')}"
    checks.append(("O1 bribe/bundle sample ranks P0", o1_ok, o1_msg))

    mint_ok = False
    mint_msg = ""
    try:
        mint = json.loads((ROOT / "output" / "o1_pancake_v3_decode" / "decoded_mint.json").read_text(encoding="utf-8"))
        mint_ok = mint.get("position_id") == 6913002 and mint.get("tick_lower") == -30991 and mint.get("tick_upper") == -10219
        mint_msg = f"position_id={mint.get('position_id')} ticks={mint.get('tick_lower')}..{mint.get('tick_upper')}"
    except Exception as exc:
        mint_msg = str(exc)
    checks.append(("O1 Pancake V3 mint decoded", mint_ok, mint_msg))

    swap_ok = False
    swap_msg = ""
    try:
        with (ROOT / "output" / "o1_pancake_v3_decode" / "decoded_swaps.csv").open("r", encoding="utf-8", newline="") as f:
            swap_rows = list(csv.DictReader(f))
        total_usdt = sum(float(row.get("usdt_in") or 0) for row in swap_rows)
        swap_ok = len(swap_rows) == 5 and 1_003_000 <= total_usdt <= 1_004_000
        swap_msg = f"{len(swap_rows)} swaps total_usdt={total_usdt:.2f}"
    except Exception as exc:
        swap_msg = str(exc)
    checks.append(("O1 opening swaps decoded", swap_ok, swap_msg))

    front_trace_ok = False
    front_trace_msg = ""
    try:
        with (ROOT / "output" / "o1_front_buyers_trace" / "front_buyers_trace.csv").open("r", encoding="utf-8", newline="") as f:
            trace_rows = list(csv.DictReader(f))
        held_rows = [row for row in trace_rows if row.get("status") == "held_or_accumulated"]
        front_trace_ok = len(trace_rows) == 5 and len(held_rows) == 5
        front_trace_msg = f"{len(held_rows)}/{len(trace_rows)} held_or_accumulated"
    except Exception as exc:
        front_trace_msg = str(exc)
    checks.append(("O1 front buyers traced", front_trace_ok, front_trace_msg))

    report = render_report(checks, lane_counts, o1_rows)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(REPORT)

    failed = [name for name, ok, _ in checks if not ok]
    if failed:
        print("failed checks:")
        for name in failed:
            print(f"- {name}")
        return 1
    return 0


def render_report(
    checks: list[tuple[str, bool, str]],
    lane_counts: dict[str, int],
    o1_rows: list[dict[str, str]],
) -> str:
    lines = [
        "# Sniper Engine Verification Report",
        "",
        "Generated by `scripts/verify_sniper_engine.py`.",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        lines.append(f"| {name} | {status} | {clean(detail)} |")

    lines.extend(["", "## Lane Counts", ""])
    for lane, count in sorted(lane_counts.items()):
        lines.append(f"- `{lane}`: {count}")

    lines.extend(["", "## O1 Sample", ""])
    if o1_rows:
        row = o1_rows[0]
        lines.extend(
            [
                f"- score: `{row.get('score')}`",
                f"- lane: `{row.get('lane')}`",
                f"- evidence: `{row.get('evidence_flags')}`",
                f"- gaps: `{row.get('gaps')}`",
                f"- next checks: `{row.get('next_checks')}`",
            ]
        )
    else:
        lines.append("- missing")

    lines.append("")
    return "\n".join(lines)


def clean(value: str) -> str:
    return (value or "").replace("\n", " ").replace("|", "/")


if __name__ == "__main__":
    raise SystemExit(main())
