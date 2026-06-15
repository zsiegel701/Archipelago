"""
Mapping from AP item names to the XML ingredient strings used in the
Order_*.xml customer order files under the game's levels directory.

Each value is the literal string (or list of strings) that appears — or needs
to appear — inside an <Item> or <Flair> element when that recipe is unlocked.

Items with no XML ingredient string (power-ups, keys, filler) are omitted;
they are handled elsewhere and do not modify the order files.
"""
from __future__ import annotations

# Ingredient strings present in the game at startup (before any AP items are
# received).  All Order_*.xml files are rewritten to contain only these plus
# whatever the player has unlocked.
#
# "Beef" and "Beef Cheese" are always available; they are the baseline burger
# recipes every customer file already references.
BASE_BURGER_STRINGS: frozenset[str] = frozenset(["Beef", "Beef Cheese"])

# ---------------------------------------------------------------------------
# Per-item XML strings
# ---------------------------------------------------------------------------
# Format: AP item name  →  string (single recipe) or list[str] (group that is
# always unlocked or removed together, e.g. three small-drink sizes).
#
# Sandwich / burger ingredients are the verbatim tokens inside a bun-contents
# <Item> element, e.g. "Beef Cheese Bacon Lettuce".
# Side, drink, sundae, and shake items are the self-contained item-IDs used by
# the engine, e.g. "LargeFries".
# Salad ingredients (lettuce / tomato / …) are the pickmult weight-list tokens
# inside a SaladIngredients element.
# Snack items are the space-separated tray-contents strings inside a snack
# <Item> element.
# Flair tokens (ketchup, mustard, hotfudge, mayo) appear inside <Flair>
# weight-list elements.

ITEM_TO_XML: dict[str, str | list[str]] = {

    # ── Chicken sandwiches ──────────────────────────────────────────────────
    # Bun-contents strings; appear in per-character ChickenSandwich items.
    "Chicken Sandwich":                         "Chicken",
    "Chicken Sandwich w/Lettuce":               "Chicken Lettuce",
    "Bacon Chicken Sandwich w/Lettuce":         "Chicken Bacon Lettuce",
    "Chicken Sandwich w/Lettuce+Tomato":        "Chicken Lettuce Tomato",
    "Bacon Chicken Sandwich w/Lettuce+Tomato":  "Chicken Bacon Lettuce Tomato",
    # Bonus: cheese variants (not in base game; "Cheese" inserts after "Chicken")
    "Chicken Sandwich w/Cheese":                        "Chicken Cheese",
    "Chicken Sandwich w/Cheese+Lettuce":                "Chicken Cheese Lettuce",
    "Bacon Chicken Sandwich w/Cheese+Lettuce":          "Chicken Cheese Bacon Lettuce",
    "Chicken Sandwich w/Cheese+Lettuce+Tomato":         "Chicken Cheese Lettuce Tomato",
    "Bacon Chicken Sandwich w/Cheese+Lettuce+Tomato":   "Chicken Cheese Bacon Lettuce Tomato",

    # ── Burgers ─────────────────────────────────────────────────────────────
    # Bun-contents strings beyond the base "Beef" / "Beef Cheese" entries.
    "Double Cheeseburger":                          "Beef Cheese Beef Cheese",
    "Hamburger w/Lettuce":                          "Beef Lettuce",
    "Hamburger w/Lettuce+Tomato":                   "Beef Lettuce Tomato",
    "Cheeseburger w/Lettuce":                       "Beef Cheese Lettuce",
    "Cheeseburger w/Lettuce+Tomato":                "Beef Cheese Lettuce Tomato",
    "BLT":                                          "Bacon Lettuce Tomato",
    "Bacon Cheeseburger":                           "Beef Cheese Bacon",
    "Bacon Cheeseburger w/Lettuce":                 "Beef Cheese Bacon Lettuce",
    "Bacon Cheeseburger w/Lettuce+Tomato":          "Beef Cheese Bacon Lettuce Tomato",
    "Double Cheeseburger w/Lettuce":                "Beef Cheese Beef Cheese Lettuce",
    "Double Bacon Cheeseburger":                    "Beef Cheese Bacon Beef Cheese Bacon",
    "Double Bacon Cheeseburger w/Lettuce":          "Beef Cheese Bacon Beef Cheese Bacon Lettuce",
    "Double Bacon Cheeseburger w/Lettuce+Tomato":   "Beef Cheese Bacon Beef Cheese Bacon Lettuce Tomato",
    "Double Cheeseburger w/Lettuce+Tomato":         "Beef Cheese Beef Cheese Lettuce Tomato",
    "Triple Cheeseburger":                           "Beef Cheese Beef Cheese Beef Cheese",
    "Triple Cheeseburger w/Lettuce":                 "Beef Cheese Beef Cheese Beef Cheese Lettuce",
    "Triple Cheeseburger w/Lettuce+Tomato":          "Beef Cheese Beef Cheese Beef Cheese Lettuce Tomato",
    "Triple Bacon Cheeseburger w/Lettuce+Tomato":    "Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon Lettuce Tomato",
    # Bonus: bacon burgers without cheese
    "Hamburger w/Bacon":                "Beef Bacon",
    "Hamburger w/Bacon+Lettuce":        "Beef Bacon Lettuce",
    "Hamburger w/Bacon+Lettuce+Tomato": "Beef Bacon Lettuce Tomato",
    # Bonus: quadruple burgers
    "Quadruple Cheeseburger":                  "Beef Cheese Beef Cheese Beef Cheese Beef Cheese",
    "Quadruple Cheeseburger w/Lettuce":        "Beef Cheese Beef Cheese Beef Cheese Beef Cheese Lettuce",
    "Quadruple Cheeseburger w/Lettuce+Tomato": "Beef Cheese Beef Cheese Beef Cheese Beef Cheese Lettuce Tomato",
    "Quadruple Bacon Cheeseburger":                    "Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon",
    "Quadruple Bacon Cheeseburger w/Lettuce+Tomato":   "Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon Lettuce Tomato",

    # ── Sides ────────────────────────────────────────────────────────────────
    "Large Fries":       "LargeFries",
    "Large Onion Rings": "LargeOnionRings",
    "Large Curly Fries": "LargeCurlyFries",
    "Small Fries":       "SmallFries",
    "Small Onion Rings": "SmallOnionRings",
    "Small Curly Fries": "SmallCurlyFries",

    # ── Drinks ──────────────────────────────────────────────────────────────
    "Large Cola":            "LargeCola",
    "Large Orange Soda":     "LargeOrangeSoda",
    "Small Cola":            "SmallCola",
    "Small Orange Soda":     "SmallOrangeSoda",
    "Small Lemon Lime Soda": "SmallLemonLimeSoda",
    "Vanilla Cola Float":    "LargeVanillaColaFloat",
    "Small Cola Float":      "SmallVanillaColaFloat",

    # Salad ingredients are controlled by Progressive Salad (see SALAD_INGREDIENT_ORDER below)
    # and are not mapped here — the xml patcher injects them based on the item count.

    # ── Snack trays ──────────────────────────────────────────────────────────
    # Space-separated tray-contents strings; match the body of snack <Item> nodes.
    "Chicken Nuggets":  "snacktray snacknugget",
    "6 Piece Nuggets":  "snacktray snacknugget snacknugget",
    "Nuggets w/Celery": "snacktray snacknugget snackcelery snackcelery",
    "Fun Meal":         "snacktray snacknugget toy",
    "Veggie Pack":      "snacktray snackcelery snackcelery snackcarrot snackcarrot",
    "Super Fun Meal":   ["snacktray snacknugget toy RandomSnackSide",
                         "snacktray snacknugget toy MomSnackSide"],  # MomSnack3 uses MomSnackSide
    "Veggie Fun Meal":  ["snacktray snackcelery snackcarrot toy RandomSnackSide",
                         "snacktray snackcelery snackcarrot toy MomSnackSide"],  # MomSnack4 uses MomSnackSide

    # ── Ice cream sundaes ────────────────────────────────────────────────────
    "Vanilla Ice Cream":    "LargeVanillaSundae",
    "Chocolate Ice Cream":  "LargeChocolateSundae",
    "Strawberry Ice Cream": "LargeStrawberrySundae",
    # Hot Fudge is a <Flair> weight-list token on sundae items, not an order item.
    # SchoolGirlSundaeFlair and ClownSundaeFlair use the CamelCase item-ID form
    # ("HotFudge", "Sprinkles") while inline food flair uses lowercase tokens.
    # Both forms must be registered so the patcher recognises and filters each.
    "Hot Fudge": ["hotfudge", "HotFudge"],
    "Large Vanilla Shake":    "LargeVanillaShake",
    "Large Chocolate Shake":  "LargeChocolateShake",
    "Large Strawberry Shake": "LargeStrawberryShake",
    "Small Vanilla Shake":    "SmallVanillaShake",
    "Small Chocolate Shake":  "SmallChocolateShake",
    "Small Strawberry Shake": "SmallStrawberryShake",
    # Order_Clown.xml capitalises "Cherry" while all other files use lowercase.
    "Cherry":             ["cherry", "Cherry"],
    "Sprinkles":          ["sprinkles", "Sprinkles"],

    # ── Condiment flair tokens ────────────────────────────────────────────────
    # These appear in <Flair> weight-list elements for burgers/sides/snacks.
    "Ketchup": "ketchup",
    "Mustard":  "mustard",

    # ── Progression food (required for chapter 8 / alien levels) ─────────────
    # Triple Bacon Cheeseburger is the AlienBurger bun-contents string (Order_Alien.xml).
    "Triple Bacon Cheeseburger": "Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon",
    # Large Lemon Lime Soda is the second item in AlienMeal (Order_Alien.xml).
    "Large Lemon Lime Soda": "LargeLemonLimeSoda",
    # Ranch Dressing maps to "mayo" — confirmed game file name.
    "Ranch Dressing": "mayo",

}

# ---------------------------------------------------------------------------
# Progressive Salad ingredient order
# ---------------------------------------------------------------------------
# Each copy of Progressive Salad received unlocks the next ingredient in this list.
# Lettuce is always first so every salad has a valid base ingredient.
SALAD_INGREDIENT_ORDER: tuple[str, ...] = ("lettuce", "tomato", "onion", "olive", "crouton")

# ---------------------------------------------------------------------------
# Bonus item injection pairs
# ---------------------------------------------------------------------------
# Maps each bonus XML string to the base XML string whose presence triggers
# injection.  When the base entry appears anywhere in an <Item> element's
# original content (even if it is currently locked and filtered out), the bonus
# entry is appended to that element if the bonus item has been unlocked.
# These strings are not present in any original game file; the patcher adds them.
BONUS_PAIRS: dict[str, str] = {
    # Small drink/shake variants — inject alongside their large counterpart
    "SmallVanillaShake":    "LargeVanillaShake",
    "SmallChocolateShake":  "LargeChocolateShake",
    "SmallStrawberryShake": "LargeStrawberryShake",
    "SmallVanillaColaFloat":       "LargeVanillaColaFloat",
    # Cheese chicken sandwiches — inject alongside the matching non-cheese version
    "Chicken Cheese":                       "Chicken",
    "Chicken Cheese Lettuce":               "Chicken Lettuce",
    "Chicken Cheese Bacon Lettuce":         "Chicken Bacon Lettuce",
    "Chicken Cheese Lettuce Tomato":        "Chicken Lettuce Tomato",
    "Chicken Cheese Bacon Lettuce Tomato":  "Chicken Bacon Lettuce Tomato",
    # Bacon burgers without cheese — inject alongside their non-bacon counterpart
    "Beef Bacon":               "Beef",
    "Beef Bacon Lettuce":       "Beef Lettuce",
    "Beef Bacon Lettuce Tomato": "Beef Lettuce Tomato",
    # Quadruple burgers — inject alongside their triple counterpart
    "Beef Cheese Beef Cheese Beef Cheese Beef Cheese":                "Beef Cheese Beef Cheese Beef Cheese",
    "Beef Cheese Beef Cheese Beef Cheese Beef Cheese Lettuce":        "Beef Cheese Beef Cheese Beef Cheese Lettuce",
    "Beef Cheese Beef Cheese Beef Cheese Beef Cheese Lettuce Tomato": "Beef Cheese Beef Cheese Beef Cheese Lettuce Tomato",
    "Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon":                    "Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon",
    "Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon Lettuce Tomato":     "Beef Cheese Bacon Beef Cheese Bacon Beef Cheese Bacon Lettuce Tomato",
}
