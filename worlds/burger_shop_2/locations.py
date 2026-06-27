from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Location

from . import items

if TYPE_CHECKING:
    from .world import BurgerShop2World

# 120 story levels across 8 stages (15 levels each).
# Levels cycle breakfast → lunch → dinner: level n is breakfast if n%3==1,
# lunch if n%3==2, dinner if n%3==0.
# Location IDs start at 2001 to avoid colliding with Burger Shop (BS1) IDs.
LOCATION_NAME_TO_ID: dict[str, int] = {
    f"Story Level {n}": 2000 + n for n in range(1, 121)
} | {
    # Starter locations (StarterRecipes option only)
    "Starter Side":            2121,
    "Starter Soda":            2122,
    "Starter Ice Cream":       2123,
    "Starter Breakfast Drink": 2124,
    "Starter Cereal":          2125,
    "Starter Soup":            2126,
}

STARTER_LOCATION_NAMES: list[str] = [
    "Starter Side",
    "Starter Soda",
    "Starter Ice Cream",
    "Starter Breakfast Drink",
    "Starter Cereal",
    "Starter Soup",
]

# Stage groupings (8 stages × 15 levels each).
LOCATION_NAME_GROUPS: dict[str, set[str]] = {
    f"Stage {s}": {f"Story Level {n}" for n in range((s - 1) * 15 + 1, s * 15 + 1)}
    for s in range(1, 9)
} | {
    # Meal-type groupings for hint and logic use.
    "Breakfast Levels": {f"Story Level {n}" for n in range(1, 121) if n % 3 == 1},
    "Lunch Levels":     {f"Story Level {n}" for n in range(1, 121) if n % 3 == 2},
    "Dinner Levels":    {f"Story Level {n}" for n in range(1, 121) if n % 3 == 0},
}


class BurgerShop2Location(Location):
    game = "Burger Shop 2"


def get_location_names_with_ids(location_names: list[str]) -> dict[str, int | None]:
    return {name: LOCATION_NAME_TO_ID[name] for name in location_names}


def create_all_locations(world: BurgerShop2World) -> None:
    create_regular_locations(world)
    if world.options.starter_recipes:
        create_starter_locations(world)
    create_events(world)


def create_starter_locations(world: BurgerShop2World) -> None:
    menu = world.get_region("Menu")
    menu.add_locations(
        {name: LOCATION_NAME_TO_ID[name] for name in STARTER_LOCATION_NAMES},
        BurgerShop2Location,
    )


def create_regular_locations(world: BurgerShop2World) -> None:
    menu = world.get_region("Menu")
    menu.add_locations(
        get_location_names_with_ids([f"Story Level {n}" for n in range(1, 121)]),
        BurgerShop2Location,
    )


def create_events(world: BurgerShop2World) -> None:
    # Victory event. The access rule (7 keys + all customer items) is set in rules.py.
    # The client sends STATUS_GOAL only after the player physically beats levels 118–120.
    menu = world.get_region("Menu")
    menu.add_event(
        "Completed Game",
        "Victory",
        location_type=BurgerShop2Location,
        item_type=items.BurgerShop2Item,
    )
