from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import CollectionState
from worlds.generic.Rules import add_rule

from .items import LEVEL_KEY_COUNT, LEVEL_KEY_ITEM

if TYPE_CHECKING:
    from .world import BurgerShop2World

# Story levels containing DogBag customers — unsatisfiable without "Dog Biscuit"
# (item is moved off-screen in Coords.xml when locked).
# Derived from DefLevel_Test.xml; stage→level mapping: stage N starts at (N-1)*15+1,
# each X-Ya/b/c group maps to three consecutive levels.
# Stage 2 uses the 2ALT customer pools (the plain "2" pools are unused in story mode).
_DOG_BISCUIT_LEVELS: frozenset[int] = frozenset({
    # Stage 2 / 2ALT (levels 16–30)
    16, 17, 18, 20, 21, 22, 23, 25, 26, 27, 28, 29, 30,
    # Stage 3 (levels 31–45)
    38, 43, 44, 45,
    # Stage 4 (levels 46–60)
    47, 50, 55, 58, 59, 60,
    # Stage 5 (levels 61–75)
    63, 67, 73, 74, 75,
    # Stage 6 (levels 76–90)
    78, 82, 85, 88, 89, 90,
    # Stage 7 (levels 91–105)
    92, 102, 103, 104, 105,
    # Stage 8 (levels 106–120)
    110, 113, 118, 119, 120,
})

# Story levels containing OldChap customers — unsatisfiable without "Menu".
_MENU_LEVELS: frozenset[int] = frozenset({
    # Stage 1 (levels 1–15)
    10, 11, 12, 15,
    # Stage 2 / 2ALT (levels 16–30)
    17, 20, 22, 28, 29, 30,
    # Stage 3 (levels 31–45)
    33, 34, 39, 42, 43, 44, 45,
    # Stage 4 (levels 46–60)
    48, 49, 55, 58, 59, 60,
    # Stage 5 (levels 61–75)
    63, 69, 73, 74, 75,
    # Stage 6 (levels 76–90)
    81, 82, 85, 88, 89, 90,
    # Stage 7 (levels 91–105)
    93, 103, 104, 105,
    # Stage 8 (levels 106–120)
    110, 118, 119, 120,
})

# Story levels containing Annoying customers — unsatisfiable without "Shirt".
_SHIRT_LEVELS: frozenset[int] = frozenset({
    # Stage 6 (levels 76–90)
    82, 83, 84, 85, 87, 88, 89, 90,
    # Stage 7 (levels 91–105)
    94, 100, 103, 104, 105,
    # Stage 8 (levels 106–120)
    111, 115, 118, 119, 120,
})


def _make_level_rule(player: int, keys_needed: int):
    """Return an access rule for a single story level."""
    def rule(state: CollectionState) -> bool:
        return state.has(LEVEL_KEY_ITEM, player, keys_needed)
    return rule


def _make_goal_rule(player: int):
    """Return an access rule for the victory event (levels 118–120 all need 7 keys + all 3 customer items)."""
    def rule(state: CollectionState) -> bool:
        return (
            state.has(LEVEL_KEY_ITEM, player, LEVEL_KEY_COUNT)
            and state.has("Dog Biscuit", player)
            and state.has("Menu", player)
            and state.has("Shirt", player)
        )
    return rule


def set_all_rules(world: BurgerShop2World) -> None:
    set_all_location_rules(world)
    set_completion_condition(world)


def set_all_location_rules(world: BurgerShop2World) -> None:
    player = world.player
    for n in range(1, 121):
        keys_needed = (n - 1) // 15
        if keys_needed > 0:
            location = world.get_location(f"Story Level {n}")
            world.set_rule(location, _make_level_rule(player, keys_needed))

    for n in _DOG_BISCUIT_LEVELS:
        location = world.get_location(f"Story Level {n}")
        add_rule(location, lambda state, p=player: state.has("Dog Biscuit", p))

    for n in _MENU_LEVELS:
        location = world.get_location(f"Story Level {n}")
        add_rule(location, lambda state, p=player: state.has("Menu", p))

    for n in _SHIRT_LEVELS:
        location = world.get_location(f"Story Level {n}")
        add_rule(location, lambda state, p=player: state.has("Shirt", p))

    victory_location = world.get_location("Completed Game")
    world.set_rule(victory_location, _make_goal_rule(player))


def set_completion_condition(world: BurgerShop2World) -> None:
    world.set_completion_rule(lambda state: state.has("Victory", world.player))
