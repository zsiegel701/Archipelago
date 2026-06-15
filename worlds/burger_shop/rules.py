from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import CollectionState

from .items import ALIEN_FOOD_ITEMS, LEVEL_KEY_COUNT, LEVEL_KEY_ITEM

if TYPE_CHECKING:
    from .world import BurgerShopWorld


def _make_level_rule(player: int, keys_needed: int, needs_alien_food: bool):
    """Return a rule function for a single story level location."""
    if needs_alien_food:
        alien_food = ALIEN_FOOD_ITEMS

        def rule(state: CollectionState) -> bool:
            return (
                state.has(LEVEL_KEY_ITEM, player, keys_needed)
                and all(state.has(item, player) for item in alien_food)
            )

    else:
        def rule(state: CollectionState) -> bool:
            return state.has(LEVEL_KEY_ITEM, player, keys_needed)

    return rule


def set_all_rules(world: BurgerShopWorld) -> None:
    set_all_location_rules(world)
    set_completion_condition(world)


def set_all_location_rules(world: BurgerShopWorld) -> None:
    player = world.player
    for n in range(1, 81):
        # Levels 1–10 need 0 keys (always accessible); each block of 10 beyond that needs one more key.
        keys_needed = (n - 1) // 10
        needs_alien = n >= 71
        if keys_needed > 0 or needs_alien:
            location = world.get_location(f"Story Level {n}")
            world.set_rule(location, _make_level_rule(player, keys_needed, needs_alien))

    # Victory: beating level 80 requires all 7 keys and the alien food items.
    victory_location = world.get_location("Completed Game")
    world.set_rule(
        victory_location,
        _make_level_rule(player, LEVEL_KEY_COUNT, needs_alien_food=True),
    )


def set_completion_condition(world: BurgerShopWorld) -> None:
    world.set_completion_rule(lambda state: state.has("Victory", world.player))
