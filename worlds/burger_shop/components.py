from worlds.LauncherComponents import Component, Type, components, launch


def run_client(*args: str) -> None:
    from .client.burger_shop_client import main
    launch(main, name="Burger Shop Client", args=args)


components.append(
    Component(
        "Burger Shop Client",
        func=run_client,
        game_name="Burger Shop",
        component_type=Type.CLIENT,
        supports_uri=True,
    )
)
