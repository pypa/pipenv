from typing import Union

from pipenv.vendor.plette.models import Package, PackageCollection
from pipenv.vendor.tomlkit.container import Container
from pipenv.vendor.tomlkit.items import AoT, Array, Bool, InlineTable, Item, String, Table

try:
    import tomllib as toml
except ImportError:
    from pipenv.vendor import tomli as toml

from pipenv.vendor import tomlkit

TOML_DICT_TYPES = Union[Container, Package, PackageCollection, Table, InlineTable]
TOML_DICT_OBJECTS = (Container, Package, Table, InlineTable, PackageCollection)
TOML_DICT_NAMES = [o.__class__.__name__ for o in TOML_DICT_OBJECTS]


def cleanup_toml(tml):
    # Remove all empty lines from TOML.
    toml = "\n".join(line for line in tml.split("\n") if line.strip())
    new_toml = []
    # Add newlines between TOML sections.
    for i, line in enumerate(toml.split("\n")):
        # Skip the first line.
        if line.startswith("[") and i > 0:
            # Insert a newline before the heading.
            new_toml.append("")
        new_toml.append(line)
    # adding new line at the end of the TOML file
    new_toml.append("")
    toml = "\n".join(new_toml)
    return toml


def convert_toml_outline_tables(parsed, project):
    """Converts all outline tables to inline tables."""

    def convert_tomlkit_table(section):
        result = section.copy()
        if isinstance(section, tomlkit.items.Table):
            body = section.value._body
        elif isinstance(section, tomlkit.container.OutOfOrderTableProxy):
            body = section._internal_container._body
        else:
            body = section._body
        for key, value in body:
            if not key:
                continue
            if hasattr(value, "keys") and not isinstance(
                value, tomlkit.items.InlineTable
            ):
                table = tomlkit.inline_table()
                table.update(value.value)
                result[key.key] = table
        return result

    def convert_toml_table(section):
        result = section.copy()
        for package, value in section.items():
            if hasattr(value, "keys") and not isinstance(
                value, toml.decoder.InlineTableDict
            ):
                table = toml.TomlDecoder().get_empty_inline_table()
                table.update(value)
                result[package] = table
        return result

    is_tomlkit_parsed = isinstance(parsed, tomlkit.container.Container)
    for section in project.get_package_categories():
        table_data = parsed.get(section, {})
        if not table_data:
            continue
        if is_tomlkit_parsed:
            result = convert_tomlkit_table(table_data)
        else:
            result = convert_toml_table(table_data)

        parsed[section] = result
    return parsed


def tomlkit_value_to_python(toml_value):
    # type: (Union[Array, AoT, TOML_DICT_TYPES, Item]) -> Union[List, Dict]
    value_type = type(toml_value).__name__
    if (
        isinstance(toml_value, TOML_DICT_OBJECTS + (dict,))
        or value_type in TOML_DICT_NAMES
    ):
        return tomlkit_dict_to_python(toml_value)
    elif isinstance(toml_value, AoT) or value_type == "AoT":
        return [tomlkit_value_to_python(val) for val in toml_value._body]
    elif isinstance(toml_value, Array) or value_type == "Array":
        return [tomlkit_value_to_python(val) for val in list(toml_value)]
    elif isinstance(toml_value, String) or value_type == "String":
        return f"{toml_value!s}"
    elif isinstance(toml_value, Bool) or value_type == "Bool":
        return toml_value.value
    elif isinstance(toml_value, Item):
        return toml_value.value
    return toml_value


def tomlkit_dict_to_python(toml_dict):
    # type: (TOML_DICT_TYPES) -> Dict
    value_type = type(toml_dict).__name__
    if toml_dict is None:
        raise TypeError("Invalid type NoneType when converting toml dict to python")
    converted = None  # type: Optional[Dict]
    if isinstance(toml_dict, (InlineTable, Table)) or value_type in (
        "InlineTable",
        "Table",
    ):
        converted = toml_dict.value
    elif isinstance(toml_dict, (Package, PackageCollection)) or value_type in (
        "Package, PackageCollection"
    ):
        converted = toml_dict._data
        if isinstance(converted, Container) or type(converted).__name__ == "Container":
            converted = converted.value
    elif isinstance(toml_dict, Container) or value_type == "Container":
        converted = toml_dict.value
    elif isinstance(toml_dict, dict):
        converted = toml_dict.copy()
    else:
        raise TypeError(
            f"Invalid type for conversion: expected Container, Dict, or Table, got {toml_dict}"
        )
    if isinstance(converted, dict):
        return {k: tomlkit_value_to_python(v) for k, v in converted.items()}
    elif isinstance(converted, (TOML_DICT_OBJECTS)) or value_type in TOML_DICT_NAMES:
        return tomlkit_dict_to_python(converted)
    return converted
