
from prettytoml.elements import traversal as t, factory as element_factory
from prettytoml.elements.table import TableElement


def comment_space(toml_file_elements):
    """
    Rule: Line-terminating comments should always be prefixed by a single tab character whitespace only.
    """
    elements = toml_file_elements[:]
    for element in elements:
        if isinstance(element, TableElement):
            _do_table(element.sub_elements)
    return elements


def _do_table(table_elements):

    # Iterator index
    i = float('-inf')

    def next_newline():
        return t.find_following(table_elements, t.predicates.newline, i)

    def next_comment():
        return t.find_following(table_elements, t.predicates.comment, i)

    def last_non_metadata():
        return t.find_previous(table_elements, t.predicates.non_metadata, next_comment())

    while next_comment() >= 0:
        if i < last_non_metadata() < next_comment() < next_newline():
            del table_elements[last_non_metadata()+1:next_comment()]
            table_elements.insert(next_comment(), element_factory.create_whitespace_element(char='\t', length=1))
        i = next_newline()
