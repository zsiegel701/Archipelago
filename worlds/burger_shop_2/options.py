from dataclasses import dataclass

from Options import Choice, DefaultOnToggle, NamedRange, Toggle, PerGameCommonOptions


class FiveStarMode(DefaultOnToggle):
    """
    When enabled, a Story Level check is only sent after the player earns all 5 stars on that level.
    When disabled, any completion (regardless of star count) sends the check.
    """
    display_name = "Five Star Mode"


class StarterRecipes(Toggle):
    """
    When enabled, one random item from each of the following pools is placed into a starter location
    and added to the player's inventory after completing any story level: a large side, a large soda,
    an ice cream flavor, a breakfast drink, a cereal, a toasted item, a soup, and a dinner meat.
    Customer orders will include these items from early on, making gameplay immediately more demanding.
    """
    display_name = "Starter Recipes"


class BonusRecipes(DefaultOnToggle):
    """
    When enabled, up to 16 additional trap items are added to the item pool as filler-replacements,
    drawn randomly from: Small Vanilla/Chocolate/Strawberry Ice Cream, Small Vanilla/Chocolate/Strawberry
    Milkshake, Small Vanilla Cola Float, Chicken Sandwich w/Cheese, Hamburger w/Bacon,
    Quadruple Cheeseburger, Quadruple Bacon Cheeseburger, Mug Milk, Plain Pasta, and Dry
    Flakes/Fruity Os/Oatmeal Bowl.
    Any customer who could order a similar item
    will be able to order the bonus version once it is unlocked.
    """
    display_name = "Bonus Recipes"


class StartWithLollipops(DefaultOnToggle):
    """
    When enabled, Lollipops are added to the player's starting inventory. This is recommended
    when Five Star Mode is enabled, otherwise the late-game will be very difficult.
    """
    display_name = "Start with Lollipops"


class StartWithBurgerBot(Toggle):
    """
    When enabled, BurgerBot is added to the player's starting inventory. This can make late-game
    levels easier when Five Star Mode is enabled.
    """
    display_name = "Start with BurgerBot"


class CustomerSlots(NamedRange):
    """
    Forces every story level to use the same number of customer slots — the positions in the
    queue that can hold a waiting customer at once. More slots means more simultaneous orders
    and greater difficulty.

    If more than 4 customer slots are being used, expect to see a great difficulty spike in the late-game.

    Leave this at "vanilla" or 0 to keep each level's original count. Any value from 2 to 9 overrides every level, including
    the ones that specify their own count.
    """
    display_name = "Customer Slots"
    range_start = 2
    range_end = 9
    special_range_names = {"vanilla": 0}
    default = 0


class CharacterRandomization(Choice):
    """
    Randomizes which customer characters show up in each level. Every level keeps the same
    total number of customers.

    vanilla: each level uses its original cast.

    shuffle_groups: each group of customers becomes a different character of the same size,
    so "4 Sumo, 4 Clown" might become "4 Hippy, 4 Punk". Levels keep their original shape.

    randomize_counts: only the level's customer total is preserved. Both the number of
    characters and how many of each are re-rolled, so "4 Sumo, 4 Clown" could become
    "8 Hippy" or "2 Punk, 1 Skater, 3 Mimic, 2 Cowboy".
    """
    display_name = "Character Randomization"
    option_vanilla = 0
    option_shuffle_groups = 1
    option_randomize_counts = 2
    default = 0


@dataclass
class BurgerShop2Options(PerGameCommonOptions):
    five_star_mode: FiveStarMode
    starter_recipes: StarterRecipes
    bonus_recipes: BonusRecipes
    start_with_lollipops: StartWithLollipops
    start_with_burgerbot: StartWithBurgerBot
    customer_slots: CustomerSlots
    character_randomization: CharacterRandomization
