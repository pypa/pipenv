try:
    import tomllib
except ImportError:
    try:
        import pipenv.patched.pip._vendor.tomli as tomllib  # type: ignore[no-redef, unused-ignore]
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment, unused-ignore]

__all__ = ("tomllib",)
