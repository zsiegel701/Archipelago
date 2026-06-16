from dataclasses import dataclass

from Options import DefaultOnToggle, Toggle, PerGameCommonOptions


class FiveStarMode(DefaultOnToggle):
    """
    When enabled, a Story Level check is only sent after the player earns all 5 stars on that level.
    When disabled, any completion (regardless of star count) sends the check.
    """
    display_name = "Five Star Mode"


class StarterRecipes(Toggle):
    """
    When enabled, a random large side, large drink, and ice cream flavor are added to the
    player's starting inventory. Customer orders will include these items after the first
    level, making gameplay immediately more demanding.
    """
    display_name = "Starter Recipes"


class BonusRecipes(DefaultOnToggle):
    """
    When enabled, a random selection of bonus recipes not present in the base game replaces
    the filler checks. These include cheese chicken sandwiches, multi-layer BLTs, quadruple
    burgers, and small shake and float variants. Any customer who could order a similar item
    will be able to order the bonus version once it is unlocked.
    """
    display_name = "Bonus Recipes"


class StartWithCookies(DefaultOnToggle):
    """
    When enabled, Cookies are added to the player's starting inventory. This is recommended
    when Five Star Mode is enabled, otherwise the late-game will be very difficult.
    """
    display_name = "Start with Cookies"


class StartWithBurgerBot(Toggle):
    """
    When enabled, BurgerBot is added to the player's starting inventory. This can make late-game 
    levels easier when Five Star Mode is enabled.
    """
    display_name = "Start with BurgerBot"


@dataclass
class BurgerShopOptions(PerGameCommonOptions):
    five_star_mode: FiveStarMode
    starter_recipes: StarterRecipes
    bonus_recipes: BonusRecipes
    start_with_cookies: StartWithCookies
    start_with_burgerbot: StartWithBurgerBot
