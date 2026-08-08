"""Deterministic customer-character shuffle for Burger Shop 2.

Imported by both the world (which needs the result to set logic rules) and the
client (which writes it into DefLevel_Test.xml), so there is exactly one
implementation and the two can never disagree about what a seed produced.

``resolve`` is a pure function of the committed vanilla tables plus (mode, seed).
It never reads the game's files, which is what lets generation -- and Universal
Tracker's regeneration -- run on machines with no Burger Shop 2 installed.
"""
from __future__ import annotations

import random

from .character_data import (
    EXTRA_POOL_CHARACTERS,
    FROZEN_CHARACTERS,
    GATED_CHARACTERS,
    STORY_LEVEL_CUSTOMER_IDS,
    UNGATED_CUSTOMER_IDS,
    VANILLA_CUSTOMERS,
)

# Must match the option values in options.py:CharacterRandomization.
VANILLA: int = 0
SHUFFLE_GROUPS: int = 1
RANDOMIZE_COUNTS: int = 2

CharacterGroups = tuple[tuple[int, str], ...]

# sorted() so the draw order never depends on dict iteration or file order.
_POOL: tuple[str, ...] = tuple(sorted({
    name
    for groups in VANILLA_CUSTOMERS.values()
    for _, name in groups
    if name.lower() not in FROZEN_CHARACTERS
} | set(EXTRA_POOL_CHARACTERS)))

# The draw pool for UNGATED_CUSTOMER_IDS: no character whose order is hidden behind an
# AP item, so those levels stay completable with nothing collected.
_UNGATED_POOL: tuple[str, ...] = tuple(
    name for name in _POOL if name.lower() not in GATED_CHARACTERS
)


def _resolve_pool(
    groups: CharacterGroups, mode: int, rng: random.Random, pool: tuple[str, ...] = _POOL,
) -> CharacterGroups:
    """Re-roll one <Customer> pool, leaving frozen characters exactly as they are."""
    frozen = {i for i, (_, name) in enumerate(groups) if name.lower() in FROZEN_CHARACTERS}
    live = [i for i in range(len(groups)) if i not in frozen]
    if not live:
        return groups

    if mode == SHUFFLE_GROUPS:
        # Each group keeps its size and gets a new character.  Sampling without
        # replacement stops two groups collapsing onto one character, so a level
        # never ends up with less variety than vanilla gave it.  The fallback is
        # reachable only for a pool trimmed by UNGATED_CUSTOMER_IDS, where a level with
        # more groups than the pool has characters has to repeat one.
        if len(live) <= len(pool):
            names = rng.sample(pool, len(live))
        else:
            names = [rng.choice(pool) for _ in live]
        out = list(groups)
        for i, name in zip(live, names):
            out[i] = (groups[i][0], name)
        return tuple(out)

    # RANDOMIZE_COUNTS: keep only the number of non-frozen customers, then re-roll
    # both how many characters share them and how they are divided up.
    total = sum(groups[i][0] for i in live)
    if total < 1:
        return groups
    count = rng.randint(1, min(len(pool), total))
    names = rng.sample(pool, count)
    # Random composition of `total` into `count` parts of at least 1 (stars and bars).
    cuts = sorted(rng.sample(range(1, total), count - 1)) if count > 1 else []
    sizes = [b - a for a, b in zip([0] + cuts, cuts + [total])]
    new_groups = [(size, name) for size, name in zip(sizes, names)]

    # Frozen groups keep their slots; the new groups take over the first live slot.
    out: list[tuple[int, str]] = []
    placed = False
    for i, group in enumerate(groups):
        if i in frozen:
            out.append(group)
        elif not placed:
            out.extend(new_groups)
            placed = True
    return tuple(out)


def resolve(mode: int, seed: int) -> dict[str, CharacterGroups]:
    """Return the full <Customer> id -> groups mapping for this (mode, seed)."""
    if mode == VANILLA:
        return dict(VANILLA_CUSTOMERS)
    rng = random.Random(seed)
    return {
        customer_id: _resolve_pool(
            groups, mode, rng,
            _UNGATED_POOL if customer_id in UNGATED_CUSTOMER_IDS else _POOL,
        )
        for customer_id, groups in VANILLA_CUSTOMERS.items()
    }


def gated_levels(mapping: dict[str, CharacterGroups]) -> dict[str, frozenset[int]]:
    """Return AP item name -> the story levels that cannot be completed without it.

    A level is gated when its pool contains a character who orders an item that is
    hidden until the matching AP item arrives (see GATED_CHARACTERS).
    """
    found: dict[str, set[int]] = {item: set() for item in GATED_CHARACTERS.values()}
    for level, customer_id in enumerate(STORY_LEVEL_CUSTOMER_IDS, 1):
        for _, name in mapping.get(customer_id, ()):
            item = GATED_CHARACTERS.get(name.lower())
            if item is not None:
                found[item].add(level)
    return {item: frozenset(levels) for item, levels in found.items()}
