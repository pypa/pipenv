class AbstractProvider(object):
    """Delegate class to provide requirment interface for the resolver.
    """
    def identify(self, dependency):
        """Given a dependency, return an identifier for it.

        This is used in many places to identify the dependency, e.g. whether
        two requirements should have their specifier parts merged, whether
        two specifications would conflict with each other (because they the
        same name but different versions).
        """
        raise NotImplementedError

    def get_preference(self, resolution, candidates, information):
        """Produce a sort key for given specification based on preference.

        The preference is defined as "I think this requirement should be
        resolved first". The lower the return value is, the more preferred
        this group of arguments is.

        :param resolution: Currently pinned candidate, or `None`.
        :param candidates: A list of possible candidates.
        :param information: A list of requirement information.

        Each information instance is a named tuple with two entries:

        * `requirement` specifies a requirement contributing to the current
          candidate list
        * `parent` specifies the candidate that provids (dependend on) the
          requirement, or `None` to indicate a root requirement.

        The preference could depend on a various of issues, including (not
        necessarily in this order):

        * Is this package pinned in the current resolution result?
        * How relaxed is the requirement? Stricter ones should probably be
          worked on first? (I don't know, actually.)
        * How many possibilities are there to satisfy this requirement? Those
          with few left should likely be worked on first, I guess?
        * Are there any known conflicts for this requirement? We should
          probably work on those with the most known conflicts.

        A sortable value should be returned (this will be used as the `key`
        parameter of the built-in sorting function). The smaller the value is,
        the more preferred this specification is (i.e. the sorting function
        is called with `reverse=False`).
        """
        raise NotImplementedError

    def find_matches(self, requirement):
        """Find all possible candidates that satisfy a requirement.

        This should try to get candidates based on the requirement's type.
        For VCS, local, and archive requirements, the one-and-only match is
        returned, and for a "named" requirement, the index(es) should be
        consulted to find concrete candidates for this requirement.

        The returned candidates should be sorted by reversed preference, e.g.
        the latest should be LAST. This is done so list-popping can be as
        efficient as possible.
        """
        raise NotImplementedError

    def is_satisfied_by(self, requirement, candidate):
        """Whether the given requirement can be satisfied by a candidate.

        A boolean should be retuened to indicate whether `candidate` is a
        viable solution to the requirement.
        """
        raise NotImplementedError

    def get_dependencies(self, candidate):
        """Get dependencies of a candidate.

        This should return a collection of requirements that `candidate`
        specifies as its dependencies.
        """
        raise NotImplementedError
