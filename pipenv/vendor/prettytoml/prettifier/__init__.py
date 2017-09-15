from . import deindentanonymoustable, tableindent, tableassignment
from prettytoml.prettifier import tablesep, commentspace, linelength, tableentrysort

"""
    TOMLFile prettifiers

    Each prettifier is a function that accepts a sequence of Element instances that make up a
    TOML file and it is allowed to modify it as it pleases.
"""


UNIFORM_TABLE_INDENTATION = tableindent.table_entries_should_be_uniformly_indented
UNIFORM_TABLE_ASSIGNMENT_SPACING = tableassignment.table_assignment_spacing
ANONYMOUS_TABLE_INDENTATION = deindentanonymoustable.deindent_anonymous_table
COMMENT_SPACING = commentspace.comment_space
TABLE_SPACING = tablesep.table_separation
LINE_LENGTH_ENFORCERS = linelength.line_length_limiter
TABLE_ENTRY_SORTING = tableentrysort.sort_table_entries


ALL = (
    TABLE_SPACING,      # Must be before COMMENT_SPACING
    COMMENT_SPACING,    # Must be after TABLE_SPACING
    UNIFORM_TABLE_INDENTATION,
    UNIFORM_TABLE_ASSIGNMENT_SPACING,
    ANONYMOUS_TABLE_INDENTATION,
    LINE_LENGTH_ENFORCERS,
    TABLE_ENTRY_SORTING,
)


def prettify(toml_file_elements, prettifiers=ALL):
    """
    Prettifies a sequence of element instances according to pre-defined set of formatting rules.
    """
    elements = toml_file_elements[:]
    for prettifier in prettifiers:
        elements = prettifier(elements)
    return elements
