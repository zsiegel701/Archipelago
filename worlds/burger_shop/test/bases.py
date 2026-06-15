from test.bases import WorldTestBase

from ..world import BurgerShopWorld


class BurgerShopTestBase(WorldTestBase):
    game = "Burger Shop"
    world: BurgerShopWorld
