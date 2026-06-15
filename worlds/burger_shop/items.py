from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Item, ItemClassification

if TYPE_CHECKING:
    from .world import BurgerShopWorld

LEVEL_KEY_ITEM: str = "Progressive Burger Shop"
# Levels 1–10 are always accessible; each key unlocks the next block of 10 levels.
LEVEL_KEY_COUNT: int = 7

SALAD_PROGRESSIVE_ITEM: str = "Progressive Salad"
# Each copy unlocks one more salad ingredient in a fixed order (lettuce always first).
SALAD_INGREDIENT_COUNT: int = 5

# Food items required to serve Alien customers (stage 8).
ALIEN_FOOD_ITEMS: list[str] = [
    "Triple Bacon Cheeseburger",
    "Ranch Dressing",
    "Large Lemon Lime Soda",
]

# Candidate pools for the StarterRecipes option — one item is chosen at random
# from each list and added to the player's starting inventory.
STARTER_LARGE_SIDES: list[str]  = ["Large Fries", "Large Onion Rings", "Large Curly Fries"]
STARTER_LARGE_DRINKS: list[str] = ["Large Cola", "Large Orange Soda", "Vanilla Cola Float"]
STARTER_ICE_CREAMS: list[str]   = ["Vanilla Ice Cream", "Chocolate Ice Cream", "Strawberry Ice Cream"]

# Extra recipe items unlocked by the BonusRecipes option.  These are trap items
# added explicitly to the pool; they are skipped when the option is off.
BONUS_RECIPE_ITEMS: list[str] = [
    # Small drink/shake variants
    "Small Vanilla Shake",
    "Small Chocolate Shake",
    "Small Strawberry Shake",
    "Small Cola Float",
    # Cheese chicken sandwiches (not in base game)
    "Chicken Sandwich w/Cheese",
    "Chicken Sandwich w/Cheese+Lettuce",
    "Bacon Chicken Sandwich w/Cheese+Lettuce",
    "Chicken Sandwich w/Cheese+Lettuce+Tomato",
    "Bacon Chicken Sandwich w/Cheese+Lettuce+Tomato",
    # Bacon burgers without cheese
    "Hamburger w/Bacon",
    "Hamburger w/Bacon+Lettuce",
    "Hamburger w/Bacon+Lettuce+Tomato",
    # Quadruple burgers
    "Quadruple Cheeseburger",
    "Quadruple Cheeseburger w/Lettuce",
    "Quadruple Cheeseburger w/Lettuce+Tomato",
    "Quadruple Bacon Cheeseburger",
    "Quadruple Bacon Cheeseburger w/Lettuce+Tomato",
]

# fmt: off
ITEM_NAME_TO_ID: dict[str, int] = {
    # ── Keys (1) ──────────────────────────────────────────────────────────────
    # N keys unlocks story levels 1–10+(N×10). 7 copies placed in the pool.
    "Progressive Burger Shop":  1,

    # ── Progression food (2–4) ────────────────────────────────────────────────
    "Triple Bacon Cheeseburger":    2,
    "Ranch Dressing":               3,
    "Large Lemon Lime Soda":        4,

    # ── Trap: chicken sandwiches (5–9) ───────────────────────────────────────
    "Chicken Sandwich":                         5,
    "Chicken Sandwich w/Lettuce":               6,
    "Bacon Chicken Sandwich w/Lettuce":         7,
    "Chicken Sandwich w/Lettuce+Tomato":        8,
    "Bacon Chicken Sandwich w/Lettuce+Tomato":  9,

    # ── Trap: burgers (10–27) ────────────────────────────────────────────────
    "Double Cheeseburger":                          10,
    "Hamburger w/Lettuce":                          11,
    "Hamburger w/Lettuce+Tomato":                   12,
    "Cheeseburger w/Lettuce":                       13,
    "Cheeseburger w/Lettuce+Tomato":                14,
    "BLT":                                          15,
    "Bacon Cheeseburger":                           16,
    "Bacon Cheeseburger w/Lettuce":                 17,
    "Bacon Cheeseburger w/Lettuce+Tomato":          18,
    "Double Cheeseburger w/Lettuce":                19,
    "Double Bacon Cheeseburger":                    20,
    "Double Bacon Cheeseburger w/Lettuce":          21,
    "Double Bacon Cheeseburger w/Lettuce+Tomato":   22,
    "Double Cheeseburger w/Lettuce+Tomato":         23,
    "Triple Cheeseburger":                          24,
    "Triple Cheeseburger w/Lettuce":                25,
    "Triple Cheeseburger w/Lettuce+Tomato":         26,
    "Triple Bacon Cheeseburger w/Lettuce+Tomato":   27,

    # ── Trap: sides (28–33) ──────────────────────────────────────────────────
    "Large Fries":       28,
    "Large Onion Rings": 29,
    "Large Curly Fries": 30,
    "Small Fries":       31,
    "Small Onion Rings": 32,
    "Small Curly Fries": 33,

    # ── Trap: drinks (34–39) ─────────────────────────────────────────────────
    "Large Cola":            34,
    "Large Orange Soda":     35,
    "Small Cola":            36,
    "Small Orange Soda":     37,
    "Small Lemon Lime Soda": 38,
    "Vanilla Cola Float":    39,

    # ── Trap: progressive salad (40) ─────────────────────────────────────────
    # 5 copies placed in the pool; each copy unlocks one more ingredient in order.
    "Progressive Salad": 40,

    # ── Trap: nuggets and meals (45–51) ──────────────────────────────────────
    "Chicken Nuggets":  45,
    "6 Piece Nuggets":  46,
    "Nuggets w/Celery": 47,
    "Fun Meal":         48,
    "Veggie Pack":      49,
    "Super Fun Meal":   50,
    "Veggie Fun Meal":  51,

    # ── Trap: ice cream and desserts (52–60) ─────────────────────────────────
    "Vanilla Ice Cream":      52,
    "Chocolate Ice Cream":    53,
    "Strawberry Ice Cream":   54,
    "Hot Fudge":              55,
    "Large Vanilla Shake":    56,
    "Large Chocolate Shake":  57,
    "Large Strawberry Shake": 58,
    "Cherry":                 59,
    "Sprinkles":              60,

    # ── Trap: condiments (61–62) ─────────────────────────────────────────────
    "Ketchup": 61,
    "Mustard":  62,

    # ── Useful (63–69) ───────────────────────────────────────────────────────
    "Workstation":    63,
    "BurgerBot":      64,
    "Cookies":        65,
    "Cookie Powerup": 66,
    "Speed Powerup":  67,
    "Happy Powerup":  68,
    "Money Powerup":  69,

    # ── Filler (70) ──────────────────────────────────────────────────────────
    "Lucky Penny": 70,

    # ── Trap: bonus recipes (71–86) ──────────────────────────────────────────
    "Small Vanilla Shake":                             71,
    "Small Chocolate Shake":                           72,
    "Small Strawberry Shake":                          73,
    "Small Cola Float":                                74,
    "Chicken Sandwich w/Cheese":                       75,
    "Chicken Sandwich w/Cheese+Lettuce":               76,
    "Bacon Chicken Sandwich w/Cheese+Lettuce":         77,
    "Chicken Sandwich w/Cheese+Lettuce+Tomato":        78,
    "Bacon Chicken Sandwich w/Cheese+Lettuce+Tomato":  79,
    "Hamburger w/Bacon":                               80,
    "Hamburger w/Bacon+Lettuce":                       81,
    "Hamburger w/Bacon+Lettuce+Tomato":                82,
    "Quadruple Cheeseburger":                          83,
    "Quadruple Cheeseburger w/Lettuce":                84,
    "Quadruple Cheeseburger w/Lettuce+Tomato":         85,
    "Quadruple Bacon Cheeseburger":                    86,
    "Quadruple Bacon Cheeseburger w/Lettuce+Tomato":   87,
}
# fmt: on

DEFAULT_ITEM_CLASSIFICATIONS: dict[str, ItemClassification] = {
    # Level Keys
    LEVEL_KEY_ITEM: ItemClassification.progression,
    # Required food (Alien levels)
    "Triple Bacon Cheeseburger": ItemClassification.progression,
    "Ranch Dressing":            ItemClassification.progression,
    "Large Lemon Lime Soda":     ItemClassification.progression,
    # Traps
    **{name: ItemClassification.trap for name in [
        "Chicken Sandwich", "Chicken Sandwich w/Lettuce", "Bacon Chicken Sandwich w/Lettuce",
        "Chicken Sandwich w/Lettuce+Tomato", "Bacon Chicken Sandwich w/Lettuce+Tomato",
        "Double Cheeseburger", "Hamburger w/Lettuce", "Hamburger w/Lettuce+Tomato",
        "Cheeseburger w/Lettuce", "Cheeseburger w/Lettuce+Tomato", "BLT",
        "Bacon Cheeseburger", "Bacon Cheeseburger w/Lettuce", "Bacon Cheeseburger w/Lettuce+Tomato",
        "Double Cheeseburger w/Lettuce", "Double Bacon Cheeseburger",
        "Double Bacon Cheeseburger w/Lettuce", "Double Bacon Cheeseburger w/Lettuce+Tomato",
        "Double Cheeseburger w/Lettuce+Tomato", "Triple Cheeseburger",
        "Triple Cheeseburger w/Lettuce", "Triple Cheeseburger w/Lettuce+Tomato",
        "Large Fries", "Large Onion Rings", "Large Curly Fries",
        "Small Fries", "Small Onion Rings", "Small Curly Fries",
        "Large Cola", "Large Orange Soda",
        "Small Cola", "Small Orange Soda", "Small Lemon Lime Soda",
        SALAD_PROGRESSIVE_ITEM,
        "Chicken Nuggets", "6 Piece Nuggets", "Nuggets w/Celery",
        "Fun Meal", "Veggie Pack", "Super Fun Meal", "Veggie Fun Meal",
        "Vanilla Ice Cream", "Chocolate Ice Cream", "Strawberry Ice Cream",
        "Hot Fudge", "Large Vanilla Shake", "Large Chocolate Shake", "Large Strawberry Shake",
        "Ketchup", "Mustard",
        "Triple Bacon Cheeseburger w/Lettuce+Tomato",
        "Vanilla Cola Float", "Cherry", "Sprinkles",
    ]},
    # Useful
    **{name: ItemClassification.useful for name in [
        "Workstation", "BurgerBot", "Cookies",
        "Cookie Powerup", "Speed Powerup", "Happy Powerup", "Money Powerup",
    ]},
    # Filler
    "Lucky Penny": ItemClassification.filler,
    # Bonus recipe traps (BonusRecipes option only)
    **{name: ItemClassification.trap for name in BONUS_RECIPE_ITEMS},
}

ITEM_NAME_GROUPS: dict[str, set[str]] = {
    "Keys": {LEVEL_KEY_ITEM},
    "Alien Food": set(ALIEN_FOOD_ITEMS),
    "Traps": {
        name for name, classification in DEFAULT_ITEM_CLASSIFICATIONS.items()
        if classification == ItemClassification.trap
    },
    "Powerups": {"Cookie Powerup", "Speed Powerup", "Happy Powerup", "Money Powerup"},
    "Bonus Recipes": set(BONUS_RECIPE_ITEMS),
}


class BurgerShopItem(Item):
    game = "Burger Shop"


def get_filler_item_name() -> str:
    return "Lucky Penny"


def create_item_with_classification(world: BurgerShopWorld, name: str) -> BurgerShopItem:
    classification = DEFAULT_ITEM_CLASSIFICATIONS[name]
    return BurgerShopItem(name, classification, ITEM_NAME_TO_ID[name], world.player)


def create_all_items(world: BurgerShopWorld) -> None:
    itempool: list[Item] = []
    # Items locked at starter locations (pre_fill) or given as start inventory must not
    # also appear in the random pool.
    locked_items: frozenset[str] = frozenset(world._starter_assignments.values()) | frozenset(world._precollected_items)

    # 7 Level Keys — each unlocks the next block of 10 story levels beyond the free first 10.
    itempool += [world.create_item(LEVEL_KEY_ITEM) for _ in range(LEVEL_KEY_COUNT)]

    # 5 Progressive Salad items — each unlocks one more salad ingredient in fixed order.
    itempool += [world.create_item(SALAD_PROGRESSIVE_ITEM) for _ in range(SALAD_INGREDIENT_COUNT)]

    # One copy of every non-filler, non-bonus item (excluding locked starters and multi-copy items).
    for name, classification in DEFAULT_ITEM_CLASSIFICATIONS.items():
        if classification == ItemClassification.filler or name in (LEVEL_KEY_ITEM, SALAD_PROGRESSIVE_ITEM):
            continue
        if name in BONUS_RECIPE_ITEMS:
            continue  # Handled below as filler-replacements.
        if name not in locked_items:
            itempool.append(world.create_item(name))

    # Fill remaining slots with a random draw from bonus recipes (when enabled),
    # falling back to Lucky Penny for any slots the bonus pool doesn't cover.
    unfilled = len(world.multiworld.get_unfilled_locations(world.player))
    needed_filler = unfilled - len(itempool)
    if world.options.bonus_recipes and BONUS_RECIPE_ITEMS:
        chosen = world.random.sample(BONUS_RECIPE_ITEMS, min(needed_filler, len(BONUS_RECIPE_ITEMS)))
        itempool += [world.create_item(name) for name in chosen]
        needed_filler -= len(chosen)
    itempool += [world.create_filler() for _ in range(max(0, needed_filler))]

    world.multiworld.itempool += itempool
