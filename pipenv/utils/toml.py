import toml
import tomlkit


def cleanup_toml(tml):
    toml = tml.split("\n")
    new_toml = []
    # Remove all empty lines from TOML.
    for line in toml:
        if line.strip():
            new_toml.append(line)
    toml = "\n".join(new_toml)
    new_toml = []
    # Add newlines between TOML sections.
    for i, line in enumerate(toml.split("\n")):
        # Skip the first line.
        if line.startswith("["):
            if i > 0:
                # Insert a newline before the heading.
                new_toml.append("")
        new_toml.append(line)
    # adding new line at the end of the TOML file
    new_toml.append("")
    toml = "\n".join(new_toml)
    return toml


def convert_toml_outline_tables(parsed):
    """Converts all outline tables to inline tables."""

    def convert_tomlkit_table(section):
        if isinstance(section, tomlkit.items.Table):
            body = section.value._body
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
                section[key.key] = table

    def convert_toml_table(section):
        for package, value in section.items():
            if hasattr(value, "keys") and not isinstance(
                value, toml.decoder.InlineTableDict
            ):
                table = toml.TomlDecoder().get_empty_inline_table()
                table.update(value)
                section[package] = table

    is_tomlkit_parsed = isinstance(parsed, tomlkit.container.Container)
    for section in ("packages", "dev-packages"):
        table_data = parsed.get(section, {})
        if not table_data:
            continue
        if is_tomlkit_parsed:
            convert_tomlkit_table(table_data)
        else:
            convert_toml_table(table_data)

    return parsed
