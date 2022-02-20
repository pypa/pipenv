if __name__ == "__main__":  # pragma: no cover
    from pipenv.patched.notpip._vendor.rich.console import Console
    from pipenv.patched.notpip._vendor.rich import inspect

    console = Console()
    inspect(console)
