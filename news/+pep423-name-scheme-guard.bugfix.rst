Fixed a latent bug in ``pipenv.utils.dependencies.pep423_name`` whose
scheme-token guard had an inverted predicate, making the branch that
preserves URL/VCS specifiers (e.g. ``git+ssh://host/path/some_repo``)
from underscore-mangling unreachable. The predicate is now correct;
bare package names continue to be lowercased and have ``_`` rewritten
to ``-`` as before. The sibling helper ``normalize_name`` in
``pipenv.utils.requirements`` has been removed and its four callers
migrated to ``pep423_name``.
