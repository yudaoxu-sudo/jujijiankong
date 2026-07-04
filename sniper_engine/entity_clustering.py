from __future__ import annotations

from collections import defaultdict
from typing import Any

from sniper_engine.address_labels import global_address_label
from sniper_engine.exchange_aggregator import EXCHANGE_AGGREGATOR_CLASSES


NON_UNION_PARENT_CLASSES = {
    "bridge",
    "bridge_contract",
    "cex",
    "cex_deposit",
    "cex_hot_wallet",
    "contract",
    "dex_quoter",
    "dex_router",
    "dex_vault",
    "exchange",
    *EXCHANGE_AGGREGATOR_CLASSES,
    "lp_locker_or_staking",
    "lp_position_manager",
    "permit2",
    "pool_manager",
    "quote_token",
    "unknown_contract_pending_bearish",
}


def norm(value: str | None) -> str:
    return str(value or "").strip().lower()


def is_address(value: str | None) -> bool:
    text = norm(value)
    return len(text) == 42 and text.startswith("0x") and all(ch in "0123456789abcdef" for ch in text[2:])


def funding_source_class(chain: str, address: str, extra_labels: dict[str, Any] | None = None) -> str:
    address = norm(address)
    if not is_address(address):
        return "invalid"
    if extra_labels and address in extra_labels:
        row = extra_labels[address]
        if isinstance(row, dict):
            return str(row.get("class") or row.get("destination_class") or "").strip()
        return str(row).strip()
    row = global_address_label(chain, address)
    if row:
        return str(row.get("class") or "").strip()
    return ""


def can_use_as_funding_cluster_parent(chain: str, address: str, extra_labels: dict[str, Any] | None = None) -> bool:
    label_class = funding_source_class(chain, address, extra_labels)
    if label_class in {"", "eoa", "eoa_or_unlabeled"}:
        return is_address(address)
    return label_class not in NON_UNION_PARENT_CLASSES


def row_address(row: dict[str, Any]) -> str:
    for key in ("address", "wallet", "buyer", "holder", "recipient", "to"):
        address = norm(row.get(key))
        if is_address(address):
            return address
    return ""


def row_funding_source(row: dict[str, Any]) -> str:
    for key in ("funding_source", "funder", "source", "funded_by", "parent", "first_funder"):
        address = norm(row.get(key))
        if is_address(address):
            return address
    return ""


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, value: str) -> None:
        if value not in self.parent:
            self.parent[value] = value

    def find(self, value: str) -> str:
        self.add(value)
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            next_value = self.parent[value]
            self.parent[value] = root
            value = next_value
        return root

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def cluster_by_funding_source(
    chain: str,
    rows: list[dict[str, Any]],
    extra_labels: dict[str, Any] | None = None,
    min_cluster_size: int = 2,
) -> dict[str, Any]:
    uf = UnionFind()
    children_by_parent: dict[str, list[str]] = defaultdict(list)
    skipped_parents: dict[str, dict[str, Any]] = {}
    indexed_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        wallet = row_address(row)
        source = row_funding_source(row)
        if not wallet:
            continue
        uf.add(wallet)
        indexed_rows.append({"index": index, "wallet": wallet, "funding_source": source, "row": row})
        if not source:
            continue
        if not can_use_as_funding_cluster_parent(chain, source, extra_labels):
            source_class = funding_source_class(chain, source, extra_labels)
            item = skipped_parents.setdefault(
                source,
                {"address": source, "class": source_class, "child_count": 0, "children": set()},
            )
            item["child_count"] += 1
            item["children"].add(wallet)
            continue
        children_by_parent[source].append(wallet)
    for source, children in children_by_parent.items():
        first = children[0]
        for child in children[1:]:
            uf.union(first, child)
    members_by_root: dict[str, set[str]] = defaultdict(set)
    source_by_root: dict[str, set[str]] = defaultdict(set)
    row_indices_by_root: dict[str, set[int]] = defaultdict(set)
    for item in indexed_rows:
        wallet = item["wallet"]
        root = uf.find(wallet)
        members_by_root[root].add(wallet)
        row_indices_by_root[root].add(int(item["index"]))
        source = item["funding_source"]
        if source and source in children_by_parent:
            source_by_root[root].add(source)
    clusters = []
    for root, members in members_by_root.items():
        if len(members) < min_cluster_size:
            continue
        clusters.append(
            {
                "cluster_id": root,
                "member_count": len(members),
                "members": sorted(members),
                "funding_sources": sorted(source_by_root.get(root, set())),
                "row_indices": sorted(row_indices_by_root[root]),
            }
        )
    clusters.sort(key=lambda row: (-int(row["member_count"]), row["cluster_id"]))
    skipped = []
    for item in skipped_parents.values():
        skipped.append(
            {
                "address": item["address"],
                "class": item["class"],
                "child_count": item["child_count"],
                "children": sorted(item["children"]),
            }
        )
    skipped.sort(key=lambda row: (-int(row["child_count"]), row["address"]))
    return {
        "chain": chain,
        "input_rows": len(rows),
        "cluster_count": len(clusters),
        "clusters": clusters,
        "skipped_parent_count": len(skipped),
        "skipped_parents": skipped,
    }
