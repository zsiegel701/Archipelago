from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import ItemClassification, Location

from . import items

if TYPE_CHECKING:
    from .world import BurgerShopWorld

# Story Mode has 80 levels across 8 chapters (10 levels each).
# Level IDs start at 1001 to leave room below 1000 for item IDs.
LOCATION_NAME_TO_ID: dict[str, int] = {
    f"Story Level {n}": 1000 + n for n in range(1, 81)
} | {
    # Starter locations (StarterRecipes option only) — auto-checked by the client
    # as soon as any story level is completed.
    "Starter Side":    1081,
    "Starter Soda":    1082,
    "Starter Dessert": 1083,
}

STARTER_LOCATION_NAMES: list[str] = ["Starter Side", "Starter Soda", "Starter Dessert"]

LOCATION_NAME_GROUPS: dict[str, set[str]] = {
    "Chapter 1": {f"Story Level {n}" for n in range(1, 11)},
    "Chapter 2": {f"Story Level {n}" for n in range(11, 21)},
    "Chapter 3": {f"Story Level {n}" for n in range(21, 31)},
    "Chapter 4": {f"Story Level {n}" for n in range(31, 41)},
    "Chapter 5": {f"Story Level {n}" for n in range(41, 51)},
    "Chapter 6": {f"Story Level {n}" for n in range(51, 61)},
    "Chapter 7": {f"Story Level {n}" for n in range(61, 71)},
    "Chapter 8": {f"Story Level {n}" for n in range(71, 81)},
    # All chapter 8 levels require Triple Bacon Cheeseburger + Ranch Dressing + Large Lemon Lime Soda.
    "Alien Levels": {f"Story Level {n}" for n in range(71, 81)},
}


class BurgerShopLocation(Location):
    game = "Burger Shop"


def get_location_names_with_ids(location_names: list[str]) -> dict[str, int | None]:
    return {name: LOCATION_NAME_TO_ID[name] for name in location_names}


def create_all_locations(world: BurgerShopWorld) -> None:
    create_regular_locations(world)
    if world.options.starter_recipes:
        create_starter_locations(world)
    create_events(world)


def create_starter_locations(world: BurgerShopWorld) -> None:
    menu = world.get_region("Menu")
    menu.add_locations(
        {name: LOCATION_NAME_TO_ID[name] for name in STARTER_LOCATION_NAMES},
        BurgerShopLocation,
    )


def create_regular_locations(world: BurgerShopWorld) -> None:
    menu = world.get_region("Menu")
    all_level_locations = get_location_names_with_ids(
        [f"Story Level {n}" for n in range(1, 81)]
    )
    menu.add_locations(all_level_locations, BurgerShopLocation)


def create_events(world: BurgerShopWorld) -> None:
    # Victory event. The access rule (7 keys + alien food items) is set in
    # rules.py. The client sends STATUS_GOAL only after the player physically beats level 80.
    menu = world.get_region("Menu")
    menu.add_event(
        "Completed Game",
        "Victory",
        location_type=BurgerShopLocation,
        item_type=items.BurgerShopItem,
    )
