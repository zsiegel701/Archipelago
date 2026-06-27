"""
Burger Shop 2 recipe data.

Maps AP item names to XML identifiers used to enable/disable recipes in
customer order files (Breakfast_*.xml, Order_*.xml, Dinner_*.xml).

The client uses expert story mode (forced via the expert_mode pointer chain)
which unlocks all items automatically — no in-memory item array writes needed.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# AP item lists by meal type — used by items.py and the world generator.
# ---------------------------------------------------------------------------

BREAKFAST_RECIPES: list[str] = [
    # Sandwiches
    "Sausage Sandwich",
    "Egg Sandwich",
    "Egg Sandwich w/Bacon",
    "Egg Sandwich w/Cheese",
    "Sausage Sandwich w/Cheese",
    "Egg Sandwich w/Bacon & Cheese",
    # Cereals
    "Fruity Os Cereal",
    "Tasty Flakes Cereal",
    "Oatmeal",
    # Fruits — used in oatmeal, waffles, and dinner desserts
    "Apples",
    "Blueberries",
    "Strawberries",
    # Donuts
    "Donut",
    "Jam",          # jelly donut + toast w/jam
    "Sugar",        # powdered donut + waffle sugar
    # Toast
    "Toast",
    "Toasted English Muffin",
    # Waffles
    "Waffles",
    "Syrup",
    "Whipped Cream",    # waffles + hot chocolate + dinner desserts
    # Sides
    "Sausage Links",
    "Pancakes",
    "Home Fries",
    "Hashbrowns",
    # Drinks
    "Glass of Milk",
    "Orange Juice",
    "Coffee",
    "Hot Chocolate",
]

LUNCH_RECIPES: list[str] = [
    # Sandwiches
    "Chicken Sandwich",
    "Sandwich w/Lettuce",
    "Sandwich w/Bacon",
    "Sandwich w/Tomato",
    "BLT",
    "Double Cheeseburger",
    "Double Bacon Cheeseburger",
    "Triple Cheeseburger",
    "Triple Bacon Cheeseburger",
    # Nuggets / snacks
    "Chicken Nuggets",
    "Nuggets w/Celery",
    "Fun Meal",
    "Veggie Pack",
    "Super Fun Meal",
    "Veggie Fun Meal",
    # Salads
    "Simple Salad",
    "Salad Onions",
    "Salad Tomato",
    "Salad Croutons",
    # Sides
    "Large Fries",
    "Large Onion Rings",
    "Large Curly Fries",
    "Small Fries",
    "Small Onion Rings",
    "Small Curly Fries",
    # Drinks
    "Large Cola",
    "Large Orange Soda",
    "Large Lemon Lime Soda",
    "Small Cola",
    "Small Orange Soda",
    "Small Lemon Lime Soda",
    # Ice cream / sundae
    "Vanilla Ice Cream",
    "Chocolate Ice Cream",
    "Strawberry Ice Cream",
    "Cherry",
    "Hot Fudge",
    "Sprinkles",
    "Vanilla Milkshake",
    "Chocolate Milkshake",
    "Strawberry Milkshake",
    "Vanilla Cola Float",
    # Condiments
    "Ketchup",
    "Mustard",
    "Ranch Dressing",
]

DINNER_RECIPES: list[str] = [
    # Grilled meats
    "Grilled Chicken",
    "Grilled Ham",
    "Rib Steak",
    "Salmon",
    "Steak",
    "Gravy",
    # Pasta / Italian
    "Pasta with Tomato Sauce",
    "Mac N Cheese",
    # Pizza
    "Cheese Pizza",
    "Pepperoni",
    "Olives",
    "Green Peppers",
    "Mushrooms",
    # Vegetables / sides
    "Carrots",
    "Peas",
    "Mashed Potatoes",
    "Baked Potato",
    "Peas and Carrots",
    # Other mains
    "Lasagna",
    "Chicken Strips",
    "Shrimp",
    "Dinner Rolls",
    # Desserts
    "Desserts",
    "More Desserts",
    # Soups
    "Chicken Soup",
    "Potato Soup",
    "Tomato Soup",
    # Shared toppings — baked potato + soup (same XML ID in both contexts)
    "Dinner Cheese",    # baked potato w/cheese + cheesy soup
    "Bacon Bits",       # baked potato w/bacon + soup w/bacon bits
    "Green Onions",     # baked potato w/green onions + soup w/green onions
]

ALL_RECIPES: list[str] = BREAKFAST_RECIPES + LUNCH_RECIPES + DINNER_RECIPES

# ---------------------------------------------------------------------------
# Base XML ingredient IDs that are always available regardless of AP progress.
# These are excluded from _ALL_AP_XML_IDS so the standard entry-blocking logic
# never gates them — allowing breakfast plate flairs (which share tokens with AP
# sandwich ingredients) to pass through unconditionally.
#
# Breakfast: SausagePatty, EggFried, Bacon — also appear in ITEM_TO_XML_ID, so
#   they ARE added to the unlocked set when the corresponding AP item is received.
#   _entry_is_blocked re-checks them in sandwich context via _SANDWICH_GATE_XML_IDS,
#   so breakfast sandwich orders are still properly gated while plate flair chains
#   (which share the same ingredient tokens) always pass.
# Lunch: San_Hamburger, San_Cheeseburger — prune="false" in ComplexItems.xml.
# Dinner: SteakFries, Parsley, CornCob, MeatLoaf, Phouseroll — always-available
#   sides/garnishes that are not in the AP pool.
# ---------------------------------------------------------------------------
BREAKFAST_BASE_XML_IDS: frozenset[str] = frozenset({"SausagePatty", "EggFried", "Bacon"})
DINNER_BASE_XML_IDS: frozenset[str] = frozenset({"SteakFries", "Parsley", "CornCob", "MeatLoaf", "Phouseroll"})

# ---------------------------------------------------------------------------
# XML identifier mapping
# Maps AP item name → list of XML item/flair IDs in the customer order files.
# ---------------------------------------------------------------------------

ITEM_TO_XML_ID: dict[str, list[str]] = {
    # --- BREAKFAST ---
    # Ingredient tokens (EggFried, SausagePatty, Bacon) are included so that if a
    # BreakfastSandwich item body contains these tokens (sandwich context), the entry
    # is blocked until the AP item is received.  The configid wrappers (San_BreakEgg
    # etc.) gate the sandwich pool entries directly (they are in _ALL_AP_XML_IDS).
    "Sausage Sandwich":                 ["SausagePatty", "San_BreakSausage"],
    "Egg Sandwich":                     ["EggFried",     "San_BreakEgg"],
    "Egg Sandwich w/Bacon":             ["Bacon",        "San_BreakEggBacon"],
    "Egg Sandwich w/Cheese":            ["San_BreakEggCheese"],
    "Sausage Sandwich w/Cheese":        ["San_BreakSausageCheese"],
    "Egg Sandwich w/Bacon & Cheese":    ["San_BreakEggBaconCheese"],
    # Cereals (with milk)
    "Fruity Os Cereal":                 ["FruityOsMilkBowl"],
    "Tasty Flakes Cereal":              ["FlakesMilkBowl"],
    "Oatmeal":                          ["OatmealMilkBowl"],
    # Fruits — shared across oatmeal, waffles, and dinner desserts
    "Apples":                           ["Apples"],
    "Blueberries":                      ["Blueberries"],
    "Strawberries":                     ["Strawberries"],
    # Donuts
    "Donut":                            ["Donut"],
    "Jam":                              ["Jam"],        # jelly donut + toast w/jam
    "Sugar":                            ["Sugar"],      # powdered donut + waffle sugar
    # Toast
    "Toast":                            ["Toast"],
    "Toasted English Muffin":           ["EnglishMuffin"],
    # Waffles
    "Waffles":                          ["Waffle"],
    "Syrup":                            ["Syrup"],
    "Whipped Cream":                    ["WhipCream"],  # waffles + hot choc + dinner desserts
    # Breakfast sides
    "Sausage Links":                    ["SausageLink"],
    "Pancakes":                         ["Pancake"],
    "Home Fries":                       ["HomeFries"],
    "Hashbrowns":                       ["Hashbrown"],
    # Breakfast drinks
    "Glass of Milk":                    ["MilkGlass"],
    "Orange Juice":                     ["OJ"],
    "Coffee":                           ["Coffee"],
    "Hot Chocolate":                    ["HotChocolate"],

    # --- LUNCH ---
    "Chicken Sandwich":                 ["San_Chicken"],
    "Sandwich w/Lettuce":               ["San_Lettuce"],
    "Sandwich w/Bacon":                 ["San_Bacon"],
    "Sandwich w/Tomato":                ["San_Tomato"],
    "BLT":                              ["San_BLT"],
    "Double Cheeseburger":              ["San_Double"],
    "Double Bacon Cheeseburger":        ["San_DoubleBacon"],
    "Triple Cheeseburger":              ["San_Triple"],
    "Triple Bacon Cheeseburger":        ["San_TripleBacon"],
    # Snacks
    "Chicken Nuggets":                  ["Snack_3Nuggets", "Snack_6Nuggets"],
    "Nuggets w/Celery":                 ["Snack_NuggetsCelery"],
    "Fun Meal":                         ["Snack_FunMeal"],
    "Veggie Pack":                      ["Snack_VeggiePack"],
    "Super Fun Meal":                   ["Snack_SuperFunMeal"],
    "Veggie Fun Meal":                  ["Snack_VeggieFunMeal"],
    # Salads
    "Simple Salad":                     ["Salad_Standard", "Salad_Hippy"],
    "Salad Onions":                     ["Onions"],
    "Salad Tomato":                     ["Tomato"],
    "Salad Croutons":                   ["Croutons"],
    # Sides
    "Large Fries":                      ["LargeFries"],
    "Large Onion Rings":                ["LargeOnionRings"],
    "Large Curly Fries":                ["LargeCurlyFries"],
    "Small Fries":                      ["SmallFries"],
    "Small Onion Rings":                ["SmallOnionRings"],
    "Small Curly Fries":                ["SmallCurlyFries"],
    # Drinks
    "Large Cola":                       ["LargeCola"],
    "Large Orange Soda":                ["LargeOrangeSoda"],
    "Large Lemon Lime Soda":            ["LargeLemonLimeSoda"],
    "Small Cola":                       ["SmallCola"],
    "Small Orange Soda":                ["SmallOrangeSoda"],
    "Small Lemon Lime Soda":            ["SmallLemonLimeSoda"],
    # Ice cream
    "Vanilla Ice Cream":                ["LargeVanillaSundae"],
    "Chocolate Ice Cream":              ["LargeChocolateSundae"],
    "Strawberry Ice Cream":             ["LargeStrawberrySundae"],
    "Cherry":                           ["cherry"],
    "Hot Fudge":                        ["HotFudge", "hotfudge"],  # donut chocolate sauce + sundae
    "Sprinkles":                        ["Sprinkles", "sprinkles"],  # donut + sundae
    "Vanilla Milkshake":                ["LargeVanillaShake"],
    "Chocolate Milkshake":              ["LargeChocolateShake"],
    "Strawberry Milkshake":             ["LargeStrawberryShake"],
    "Vanilla Cola Float":               ["LargeVanillaColaFloat"],
    # Condiments
    "Ketchup":                          ["ketchup"],
    "Mustard":                          ["mustard"],
    "Ranch Dressing":                   ["ranch"],

    # --- DINNER ---
    "Grilled Chicken":                  ["ChickenGrilled"],
    "Grilled Ham":                      ["HamGrilled"],
    "Rib Steak":                        ["RibSteakGrilled"],
    "Salmon":                           ["SalmonGrilled"],
    "Steak":                            ["SteakGrilled"],
    "Gravy":                            ["Gravy"],
    # Pasta / Italian
    "Pasta with Tomato Sauce":          ["Pasta_TomatoSauce"],
    "Mac N Cheese":                     ["Pasta_Cheese"],
    # Pizza
    "Cheese Pizza":                     ["Pizza_Cheese"],
    "Pepperoni":                        ["Pepperoni"],
    "Olives":                           ["Olives"],
    "Green Peppers":                    ["GreenPeppers"],
    "Mushrooms":                        ["Mushrooms"],
    # Vegetables / sides
    "Carrots":                          ["CarrotsBoiled"],
    "Peas":                             ["PeasBoiled"],
    "Mashed Potatoes":                  ["PotatoMashed"],
    "Baked Potato":                     ["PotatoBaked"],
    "Peas and Carrots":                 ["Veg_PeasCarrots"],
    # Other mains
    "Lasagna":                          ["Lasagna"],
    "Chicken Strips":                   ["ChickenStrip"],
    "Shrimp":                           ["Shrimp"],
    "Dinner Rolls":                     ["SplitTopRoll", "CornBread", "Kaiserroll"],
    # Desserts
    "Desserts":                         ["ApplePie", "CarrotCake", "CherryPie"],
    "More Desserts":                    ["CheeseCake", "ChocolateCake", "StrawberryCake"],
    # Soups
    "Chicken Soup":                     ["ChickenSoup"],
    "Potato Soup":                      ["PotatoSoup"],
    "Tomato Soup":                      ["TomatoSoup"],
    # Shared toppings — same XML ID used for baked potato AND soup in customer files
    "Dinner Cheese":                    ["DinnerCheese"],   # baked potato + cheesy soup
    "Bacon Bits":                       ["BaconBits"],      # baked potato + soup w/bacon bits
    "Green Onions":                     ["GreenOnions"],    # baked potato + soup w/green onions

    # --- BONUS RECIPES ---
    # Bonus sandwich configids (items defined in ComplexItems.xml; injected by patcher)
    "Quadruple Cheeseburger":       ["San_Quadruple"],
    "Quadruple Bacon Cheeseburger": ["San_QuadrupleBacon"],
    "Chicken Sandwich w/Cheese":    ["San_ChickenCheese"],
    "Hamburger w/Bacon":            ["San_HamBacon"],
    # Breakfast bonus drink (not in any original order file; injected by patcher)
    "Mug Milk":     ["MilkMug"],
    # Dinner bonus pasta (flair defined in ComplexItems.xml; injected by patcher into pasta flair pools)
    "Plain Pasta": ["PastaBoiled"],
    # Small ice creams — direct XML ID + ComplexItems.xml wrapper ID
    "Small Vanilla Ice Cream":    ["SmallVanillaSundae",    "SmVanSundae"],
    "Small Chocolate Ice Cream":  ["SmallChocolateSundae",  "SmChoSundae"],
    "Small Strawberry Ice Cream": ["SmallStrawberrySundae", "SmStrSundae"],
    # Small milkshakes / float — direct XML ID + ComplexItems.xml wrapper ID
    "Small Vanilla Milkshake":    ["SmallVanillaShake",     "SmVanShake"],
    "Small Chocolate Milkshake":  ["SmallChocolateShake",   "SmChoShake"],
    "Small Strawberry Milkshake": ["SmallStrawberryShake",  "SmStrShake"],
    "Small Vanilla Cola Float":   ["SmallVanillaColaFloat", "SmVanFloat"],
    # Dry cereals — direct XML ID + ComplexItems.xml wrapper ID
    "Dry Fruity Os Bowl":                ["FruityOsBowl",  "DryFruityOs"],
    "Dry Flakes Bowl":                  ["FlakesBowl",    "DryFlakes"],
    "Dry Oatmeal Bowl":                 ["OatmealBowl",   "DryOatmeal"],
}

# ---------------------------------------------------------------------------
# Sandwich configid map (derived from ComplexItems.xml)
# ---------------------------------------------------------------------------
SANDWICH_CONFIGID_MAP: dict[str, list[str]] = {
    # Lettuce unlocks the plain-lettuce variants; tomato-only and combos are handled
    # by SANDWICH_COMPOUND_VARIANTS so they require the individual Lettuce/Tomato items.
    "San_Lettuce":     ["San_HamburgerLettuce", "San_ChickenLettuce", "San_CheeseburgerLettuce"],
    # San_Tomato has no direct (non-compound) sandwich variants — all LettuceTomato
    # variants live in SANDWICH_COMPOUND_VARIANTS and require both Lettuce and Tomato.
    "San_Bacon":       ["San_BaconCheeseburger"],
    "San_Double":      ["San_DoubleCheeseburger"],
    "San_DoubleBacon": ["San_DoubleBaconCheeseburger"],
    "San_Triple":      ["San_TripleCheeseburger"],
    "San_TripleBacon": ["San_TripleBaconCheeseburger"],
    # Bonus recipe configids — base variant only; combos handled by SANDWICH_COMPOUND_VARIANTS
    "San_Quadruple":      ["San_QuadrupleCheeseburger"],
    "San_QuadrupleBacon": ["San_QuadrupleBaconCheeseburger"],
    "San_ChickenCheese":  ["San_ChickenCheeseSandwich"],
    "San_HamBacon":       ["San_BaconHamburger"],
}

# ---------------------------------------------------------------------------
# Sandwich compound variant requirements
# ---------------------------------------------------------------------------
# Variants that require ALL listed configids to be in the unlocked set.
# Prevents e.g. San_TripleCheeseburgerLettuceTomato from being unlocked by
# "Triple Cheeseburger" alone — "Sandwich w/Lettuce+Tomato" (San_Tomato) must
# also be received.  Used by xml_patcher._compute_unlocked.
SANDWICH_COMPOUND_VARIANTS: dict[str, list[str]] = {
    # Base lettuce+tomato variants — require both Lettuce and Tomato
    "San_HamburgerLettuceTomato":      ["San_Lettuce", "San_Tomato"],
    "San_ChickenLettuceTomato":        ["San_Lettuce", "San_Tomato"],
    "San_CheeseburgerLettuceTomato":   ["San_Lettuce", "San_Tomato"],
    # Base bacon+lettuce variants — require both Bacon and Lettuce
    "San_BaconChickenLettuce":         ["San_Bacon",   "San_Lettuce"],
    "San_BaconCheeseburgerLettuce":    ["San_Bacon",   "San_Lettuce"],
    # Base bacon+lettuce+tomato variants — require all three
    "San_BaconCheeseburgerLettuceTomato": ["San_Bacon", "San_Lettuce", "San_Tomato"],
    "San_BaconChickenLettuceTomato":      ["San_Bacon", "San_Lettuce", "San_Tomato"],
    # Double cheeseburger variants
    "San_DoubleCheeseburgerLettuce":               ["San_Double",      "San_Lettuce"],
    "San_DoubleCheeseburgerLettuceTomato":         ["San_Double",      "San_Lettuce", "San_Tomato"],
    # Double bacon cheeseburger variants
    "San_DoubleBaconCheeseburgerLettuce":          ["San_DoubleBacon", "San_Lettuce"],
    "San_DoubleBaconCheeseburgerLettuceTomato":    ["San_DoubleBacon", "San_Lettuce", "San_Tomato"],
    # Triple cheeseburger variants
    "San_TripleCheeseburgerLettuce":               ["San_Triple",      "San_Lettuce"],
    "San_TripleCheeseburgerLettuceTomato":         ["San_Triple",      "San_Lettuce", "San_Tomato"],
    # Chicken cheese variants (bonus)
    "San_ChickenCheeseLettuce":                    ["San_ChickenCheese", "San_Lettuce"],
    "San_ChickenCheeseLettuceTomato":              ["San_ChickenCheese", "San_Lettuce", "San_Tomato"],
    "San_BaconChickenCheeseLettuce":               ["San_ChickenCheese", "San_Bacon",   "San_Lettuce"],
    "San_BaconChickenCheeseLettuceTomato":         ["San_ChickenCheese", "San_Bacon",   "San_Lettuce", "San_Tomato"],
    # Quadruple cheeseburger variants (bonus)
    "San_QuadrupleCheeseburgerLettuce":            ["San_Quadruple",   "San_Lettuce"],
    "San_QuadrupleCheeseburgerLettuceTomato":      ["San_Quadruple",   "San_Lettuce", "San_Tomato"],
    # Quadruple bacon variants (bonus)
    "San_QuadrupleBaconCheeseburgerLettuceTomato": ["San_QuadrupleBacon", "San_Lettuce", "San_Tomato"],
    # Bacon hamburger variants (bonus)
    "San_BaconHamburgerLettuce":                   ["San_HamBacon",    "San_Lettuce"],
    "San_BaconHamburgerLettuceTomato":             ["San_HamBacon",    "San_Lettuce", "San_Tomato"],
    # Breakfast egg+sausage compound variants
    # Unlocked when both egg and sausage configids are simultaneously received.
    # Injected into *BreakSan pools via BONUS_PAIRS (San_BreakSausage as the base).
    "San_BreakEggSausage":       ["San_BreakEgg",       "San_BreakSausage"],
    "San_BreakEggSausageCheese": ["San_BreakEggCheese", "San_BreakSausageCheese"],
}

# ---------------------------------------------------------------------------
# Bonus item injection pairs
# ---------------------------------------------------------------------------
# Maps each bonus XML string → the base XML string whose original presence in an
# <Item> element body triggers injection when the bonus AP item is received.
# These IDs are never present in original order files; the patcher adds them.
BONUS_PAIRS: dict[str, str] = {
    # Breakfast drink variant — inject alongside its base counterpart
    "MilkMug":  "MilkGlass",
    # Quadruple cheeseburger variants — inject alongside their triple counterpart
    "San_QuadrupleCheeseburger":              "San_TripleCheeseburger",
    "San_QuadrupleCheeseburgerLettuce":       "San_TripleCheeseburgerLettuce",
    "San_QuadrupleCheeseburgerLettuceTomato": "San_TripleCheeseburgerLettuceTomato",
    # Quadruple bacon variants — both inject alongside the single triple bacon variant
    "San_QuadrupleBaconCheeseburger":                 "San_TripleBaconCheeseburger",
    "San_QuadrupleBaconCheeseburgerLettuceTomato":    "San_TripleBaconCheeseburger",
    # Chicken cheese sandwiches — inject alongside their non-cheese counterpart
    "San_ChickenCheeseSandwich":               "San_Chicken",
    "San_ChickenCheeseLettuce":                "San_ChickenLettuce",
    "San_ChickenCheeseLettuceTomato":          "San_ChickenLettuceTomato",
    "San_BaconChickenCheeseLettuce":           "San_BaconChickenLettuce",
    "San_BaconChickenCheeseLettuceTomato":     "San_BaconChickenLettuceTomato",
    # Bacon hamburger (no cheese) — inject alongside the matching plain/lettuce variant
    "San_BaconHamburger":              "San_Hamburger",
    "San_BaconHamburgerLettuce":       "San_HamburgerLettuce",
    "San_BaconHamburgerLettuceTomato": "San_HamburgerLettuceTomato",
    # Plain pasta — inject into pasta flair pools alongside Pasta_Cheese (flair injection)
    "PastaBoiled": "Pasta_Cheese",
    # Breakfast sandwich cheese variants — inject alongside their base counterpart
    "San_BreakEggCheese":       "San_BreakEgg",
    "San_BreakEggBaconCheese":  "San_BreakEggBacon",
    "San_BreakSausageCheese":   "San_BreakSausage",
    # Egg+sausage compounds — inject into any pool that originally had San_BreakSausage.
    # Using San_BreakSausage as the base excludes Hippy (egg-only pool).
    # Unlock gating is handled by SANDWICH_COMPOUND_VARIANTS in _compute_unlocked.
    "San_BreakEggSausage":       "San_BreakSausage",
    "San_BreakEggSausageCheese": "San_BreakSausage",
}

# ---------------------------------------------------------------------------
# Coords.xml ox-hiding items
# Maps AP item name → (Coords.xml type attribute, original ox value).
# When locked, the patcher sets ox to 2100000000 to move the item off-screen.
# When unlocked, ox is restored to its original value from Coords.xml.orig.
# ---------------------------------------------------------------------------
COORDS_OX_ITEMS: dict[str, tuple[str, int]] = {
    "Dog Biscuit": ("DogBiscuit", 21),
    "Shirt":       ("Shirt",      38),
    "Menu":        ("Menu",       16),
}

