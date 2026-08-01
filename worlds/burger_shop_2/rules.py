from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import CollectionState
from worlds.generic.Rules import add_rule

from .character_shuffle import gated_levels
from .items import LEVEL_KEY_COUNT, LEVEL_KEY_ITEM

if TYPE_CHECKING:
    from .world import BurgerShop2World

# The story levels gated behind Dog Biscuit / Menu / Shirt are derived from the
# resolved character mapping rather than hard-coded, because the Character
# Randomization option can move DogBag, OldChap, and Annoying to other levels.
# character_shuffle.gated_levels() reproduces the vanilla sets exactly when the
# option is off.


def _make_level_rule(player: int, keys_needed: int):
    """Return an access rule for a single story level."""
    def rule(state: CollectionState) -> bool:
        return state.has(LEVEL_KEY_ITEM, player, keys_needed)
    return rule


# Victory is beating the last three story levels, so the goal needs whatever gates them.
_GOAL_LEVELS: frozenset[int] = frozenset({118, 119, 120})


def _make_goal_rule(player: int, required_items: frozenset[str]):
    """Return an access rule for the victory event: all 7 keys plus whatever gates 118–120.

    In vanilla those levels contain OldChap, DogBag, and Annoying, so this requires all
    three customer items; under randomization it requires exactly the ones that moved there.
    """
    items = tuple(sorted(required_items))

    def rule(state: CollectionState) -> bool:
        return (
            state.has(LEVEL_KEY_ITEM, player, LEVEL_KEY_COUNT)
            and all(state.has(item, player) for item in items)
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

    gated = gated_levels(world.character_map)
    for item_name, levels in gated.items():
        for n in levels:
            location = world.get_location(f"Story Level {n}")
            add_rule(location, lambda state, p=player, i=item_name: state.has(i, p))

    goal_items = frozenset(item for item, levels in gated.items() if levels & _GOAL_LEVELS)
    victory_location = world.get_location("Completed Game")
    world.set_rule(victory_location, _make_goal_rule(player, goal_items))


def set_completion_condition(world: BurgerShop2World) -> None:
    world.set_completion_rule(lambda state: state.has("Victory", world.player))
