from test.bases import WorldTestBase

from ..world import BurgerShop2World


class BurgerShop2TestBase(WorldTestBase):
    game = "Burger Shop 2"
    world: BurgerShop2World
