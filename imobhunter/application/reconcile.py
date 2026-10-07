import hashlib
from dataclasses import dataclass

from imobhunter.domain.identity import identity_keys
from imobhunter.domain.models import PropertyRecord

@dataclass(frozen=True)
class PropertyCluster:
    identity: str
    records: tuple[PropertyRecord, ...]
    identity_keys: frozenset[str]

def reconcile(records: tuple[PropertyRecord, ...] | list[PropertyRecord]) -> tuple[PropertyCluster, ...]:
    records = tuple(records)
    if not records:
        return ()
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    owners: dict[str, int] = {}
    for index, record in enumerate(records):
        for key in identity_keys(record):
            if key in owners:
                union(index, owners[key])
            else:
                owners[key] = index

    groups: dict[int, list[PropertyRecord]] = {}
    for index, record in enumerate(records):
        groups.setdefault(find(index), []).append(record)

    clusters = []
    for group in groups.values():
        keys = frozenset(key for record in group for key in identity_keys(record))
        identity = hashlib.sha256("|".join(sorted(keys)).encode()).hexdigest()
        clusters.append(PropertyCluster(identity, tuple(group), keys))
    return tuple(clusters)
