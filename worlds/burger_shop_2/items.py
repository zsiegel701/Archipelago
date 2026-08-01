from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Item, ItemClassification

from .client.recipe_data import (
    BREAKFAST_RECIPES, LUNCH_RECIPES, DINNER_RECIPES, ALL_RECIPES,
)

if TYPE_CHECKING:
    from .world import BurgerShop2World

LEVEL_KEY_ITEM: str = "Progressive Burger Shop"
# Levels 1–15 are always accessible; each key unlocks the next block of 15 levels.
# 15 free + 7 × 15 = 120 total story levels.
LEVEL_KEY_COUNT: int = 7

# Candidate pools for the StarterRecipes option — one item is chosen at random
# from each list and placed in the corresponding starter location.
STARTER_LARGE_SIDES: list[str]       = ["Large Fries", "Large Onion Rings", "Large Curly Fries"]
STARTER_LARGE_DRINKS: list[str]      = ["Large Cola", "Large Orange Soda", "Large Lemon Lime Soda"]
STARTER_ICE_CREAMS: list[str]        = ["Vanilla Ice Cream", "Chocolate Ice Cream", "Strawberry Ice Cream"]
STARTER_BREAKFAST_DRINKS: list[str]  = ["Glass of Milk", "Orange Juice", "Coffee"]
STARTER_CEREALS: list[str]           = ["Fruity Os Cereal", "Tasty Flakes Cereal", "Oatmeal"]
STARTER_SOUPS: list[str]             = ["Chicken Soup", "Potato Soup", "Tomato Soup"]
STARTER_TOASTED_ITEMS: list[str]     = ["Toasted English Muffin", "Waffles", "Toast"]
STARTER_DINNER_MEATS: list[str]      = ["Grilled Chicken", "Grilled Ham", "Rib Steak", "Salmon", "Steak"]

# Extra recipe items unlocked by the BonusRecipes option.  Added as filler-replacements;
# skipped entirely when the option is off.
BONUS_RECIPE_ITEMS: list[str] = [
    # Lunch: sandwich variants
    "Chicken Sandwich w/Cheese",
    "Hamburger w/Bacon",
    "Quadruple Cheeseburger",
    "Quadruple Bacon Cheeseburger",
    # Breakfast: hot drink variant
    "Mug Milk",
    # Dinner: plain pasta (no sauce/cheese; injected into pasta flair pools)
    "Plain Pasta",
    # Small ice creams
    "Small Vanilla Ice Cream",
    "Small Chocolate Ice Cream",
    "Small Strawberry Ice Cream",
    # Small milkshakes / float
    "Small Vanilla Milkshake",
    "Small Chocolate Milkshake",
    "Small Strawberry Milkshake",
    "Small Vanilla Cola Float",
    # Breakfast: dry cereals (unlocked via prune="false" wrappers DryFlakes/DryFruityOs/DryOatmeal)
    "Dry Flakes Bowl",
    "Dry Fruity Os Bowl",
    "Dry Oatmeal Bowl",
]

# fmt: off
ITEM_NAME_TO_ID: dict[str, int] = {
    # ── Key (1) ───────────────────────────────────────────────────────────────
    "Progressive Burger Shop": 1,

    # ── Progression customer items (2–4) ─────────────────────────────────────
    "Dog Biscuit": 2,
    "Shirt":       3,
    "Menu":        4,

    # ── Useful (5–13) ─────────────────────────────────────────────────────────
    "Lollipops":        5,
    "BurgerBot":        6,
    "Lollipop Powerup": 7,
    "Speed Powerup":    8,
    "Happy Powerup":    9,   # PowerupFreq_HappyGas in game files
    "Money Powerup":    10,
    "Freeze Powerup":   11,  # PowerupFreq_AllHappy in game files
    "Cone Powerup":     12,  # PowerupFreq_CloseSlot in game files
    "Workstation":      13,  # WorkStation element in Layout*.xml (machine id "workstation")

    # ── Filler (14) ───────────────────────────────────────────────────────────
    "Lucky Penny": 14,

    # ── Breakfast recipe traps (15–42) ────────────────────────────────────────
    # List order in bs2_recipe_data.BREAKFAST_RECIPES determines IDs; do not reorder.
    **{name: idx for idx, name in enumerate(BREAKFAST_RECIPES, start=15)},

    # ── Lunch recipe traps (43–86) ────────────────────────────────────────────
    # List order in bs2_recipe_data.LUNCH_RECIPES determines IDs; do not reorder.
    **{name: idx for idx, name in enumerate(LUNCH_RECIPES, start=43)},

    # ── Dinner recipe traps (87–116) ─────────────────────────────────────────
    # List order in bs2_recipe_data.DINNER_RECIPES determines IDs; do not reorder.
    **{name: idx for idx, name in enumerate(DINNER_RECIPES, start=87)},

    # ── Bonus recipe traps (117–132) ─────────────────────────────────────────
    # List order in BONUS_RECIPE_ITEMS determines IDs; do not reorder.
    **{name: idx for idx, name in enumerate(BONUS_RECIPE_ITEMS, start=117)},
}
# fmt: on

DEFAULT_ITEM_CLASSIFICATIONS: dict[str, ItemClassification] = {
    # Level key
    LEVEL_KEY_ITEM: ItemClassification.progression,
    # Customer items — gates specific customer types
    "Dog Biscuit": ItemClassification.progression,
    "Shirt":       ItemClassification.progression,
    "Menu":        ItemClassification.progression,
    # Useful
    **{name: ItemClassification.useful for name in [
        "Lollipops", "BurgerBot", "Workstation",
        "Lollipop Powerup", "Speed Powerup", "Happy Powerup", "Money Powerup",
        "Freeze Powerup", "Cone Powerup"
    ]},
    # Filler
    "Lucky Penny": ItemClassification.filler,
    # All recipe items are traps (they complicate orders)
    **{name: ItemClassification.trap for name in ALL_RECIPES},
    # Bonus recipe traps (BonusRecipes option only)
    **{name: ItemClassification.trap for name in BONUS_RECIPE_ITEMS},
}

ITEM_NAME_GROUPS: dict[str, set[str]] = {
    "Keys": {LEVEL_KEY_ITEM},
    "Customer Items": {"Dog Biscuit", "Shirt", "Menu"},
    "Powerups": {
        "Lollipop Powerup", "Speed Powerup", "Happy Powerup",
        "Money Powerup", "Freeze Powerup", "Cone Powerup",
    },
    "Breakfast Recipes": set(BREAKFAST_RECIPES),
    "Lunch Recipes":     set(LUNCH_RECIPES),
    "Dinner Recipes":    set(DINNER_RECIPES),
    "Bonus Recipes":     set(BONUS_RECIPE_ITEMS),
    "Traps": {
        name for name, classification in DEFAULT_ITEM_CLASSIFICATIONS.items()
        if classification == ItemClassification.trap
    },
}


class BurgerShop2Item(Item):
    game = "Burger Shop 2"


def get_filler_item_name() -> str:
    return "Lucky Penny"


def create_item_with_classification(world: BurgerShop2World, name: str) -> BurgerShop2Item:
    classification = DEFAULT_ITEM_CLASSIFICATIONS[name]
    return BurgerShop2Item(name, classification, ITEM_NAME_TO_ID[name], world.player)


def create_all_items(world: BurgerShop2World) -> None:
    itempool: list[Item] = []
    locked_items: frozenset[str] = frozenset(world._precollected_items) | frozenset(
        world._starter_assignments.values()
    )

    # 7 Level Keys — each unlocks the next block of 15 story levels beyond the free first 15.
    itempool += [world.create_item(LEVEL_KEY_ITEM) for _ in range(LEVEL_KEY_COUNT)]

    # One copy of every non-filler, non-bonus item (excluding locked starters/precollected).
    for name, classification in DEFAULT_ITEM_CLASSIFICATIONS.items():
        if classification == ItemClassification.filler or name == LEVEL_KEY_ITEM:
            continue
        if name in BONUS_RECIPE_ITEMS:
            continue  # Handled below as filler-replacements.
        if name not in locked_items:
            itempool.append(world.create_item(name))

    # Fill remaining slots with a random draw from bonus recipes (when enabled),
    # falling back to Lucky Penny for any slots the bonus pool doesn't cover.
    # Subtract starter locations: they exist and appear unfilled here (pre_fill hasn't
    # run yet), but each will be filled by place_locked_item in pre_fill, so they must
    # not be counted as open pool slots.
    unfilled = (
        len(world.multiworld.get_unfilled_locations(world.player))
        - len(world._starter_assignments)
    )
    needed_filler = unfilled - len(itempool)
    if world.options.bonus_recipes and BONUS_RECIPE_ITEMS:
        chosen = world.random.sample(BONUS_RECIPE_ITEMS, min(needed_filler, len(BONUS_RECIPE_ITEMS)))
        itempool += [world.create_item(name) for name in chosen]
        needed_filler -= len(chosen)
    itempool += [world.create_filler() for _ in range(needed_filler)]

    world.multiworld.itempool += itempool
