import collections

from .structs import DirectedGraph


RequirementInformation = collections.namedtuple('RequirementInformation', [
    'requirement', 'parent',
])


class NoVersionsAvailable(Exception):
    def __init__(self, requirement, parent):
        super(NoVersionsAvailable, self).__init__()
        self.requirement = requirement
        self.parent = parent


class RequirementsConflicted(Exception):
    def __init__(self, criterion):
        super(RequirementsConflicted, self).__init__()
        self.criterion = criterion


class Criterion(object):
    """Internal representation of possible resolution results of a package.

    This holds two attributes:

    * `information` is a collection of `RequirementInformation` pairs. Each
      pair is a requirement contributing to this criterion, and the candidate
      that provides the requirement.
    * `candidates` is a collection containing all possible candidates deducted
      from the union of contributing requirements. It should never be empty.
    """
    def __init__(self, candidates, information):
        self.candidates = candidates
        self.information = information

    @classmethod
    def from_requirement(cls, provider, requirement, parent):
        """Build an instance from a requirement.
        """
        candidates = provider.find_matches(requirement)
        if not candidates:
            raise NoVersionsAvailable(requirement, parent)
        return cls(
            candidates=candidates,
            information=[RequirementInformation(requirement, parent)],
        )

    def iter_requirement(self):
        return (i.requirement for i in self.information)

    def iter_parent(self):
        return (i.parent for i in self.information)

    def merged_with(self, provider, requirement, parent):
        """Build a new instance from this and a new requirement.
        """
        infos = list(self.information)
        infos.append(RequirementInformation(requirement, parent))
        candidates = [
            c for c in self.candidates
            if provider.is_satisfied_by(requirement, c)
        ]
        if not candidates:
            raise RequirementsConflicted(self)
        return type(self)(candidates, infos)


class ResolutionError(Exception):
    pass


class ResolutionImpossible(ResolutionError):
    def __init__(self, requirements):
        super(ResolutionImpossible, self).__init__()
        self.requirements = requirements


class ResolutionTooDeep(ResolutionError):
    def __init__(self, round_count):
        super(ResolutionTooDeep, self).__init__(round_count)
        self.round_count = round_count


# Resolution state in a round.
State = collections.namedtuple('State', 'mapping graph')


class Resolution(object):
    """Stateful resolution object.

    This is designed as a one-off object that holds information to kick start
    the resolution process, and holds the results afterwards.
    """
    def __init__(self, provider, reporter):
        self._p = provider
        self._r = reporter
        self._criteria = {}
        self._states = []

    @property
    def state(self):
        try:
            return self._states[-1]
        except IndexError:
            raise AttributeError('state')

    def _push_new_state(self):
        """Push a new state into history.

        This new state will be used to hold resolution results of the next
        coming round.
        """
        try:
            base = self._states[-1]
        except IndexError:
            graph = DirectedGraph()
            graph.add(None)     # Sentinel as root dependencies' parent.
            state = State(mapping={}, graph=graph)
        else:
            state = State(
                mapping=base.mapping.copy(),
                graph=base.graph.copy(),
            )
        self._states.append(state)

    def _contribute_to_criteria(self, name, requirement, parent):
        try:
            crit = self._criteria[name]
        except KeyError:
            crit = Criterion.from_requirement(self._p, requirement, parent)
        else:
            crit = crit.merged_with(self._p, requirement, parent)
        self._criteria[name] = crit

    def _get_criterion_item_preference(self, item):
        name, criterion = item
        try:
            pinned = self.state.mapping[name]
        except (IndexError, KeyError):
            pinned = None
        return self._p.get_preference(
            pinned, criterion.candidates, criterion.information,
        )

    def _is_current_pin_satisfying(self, name, criterion):
        try:
            current_pin = self.state.mapping[name]
        except KeyError:
            return False
        return all(
            self._p.is_satisfied_by(r, current_pin)
            for r in criterion.iter_requirement()
        )

    def _check_pinnability(self, candidate, dependencies):
        backup = self._criteria.copy()
        contributed = set()
        try:
            for subdep in dependencies:
                key = self._p.identify(subdep)
                self._contribute_to_criteria(key, subdep, parent=candidate)
                contributed.add(key)
        except RequirementsConflicted:
            self._criteria = backup
            return None
        return contributed

    def _pin_candidate(self, name, criterion, candidate, child_names):
        try:
            self.state.graph.remove(name)
        except KeyError:
            pass
        self.state.mapping[name] = candidate
        self.state.graph.add(name)
        for parent in criterion.iter_parent():
            parent_name = None if parent is None else self._p.identify(parent)
            try:
                self.state.graph.connect(parent_name, name)
            except KeyError:
                # Parent is not yet pinned. Skip now; this edge will be
                # connected when the parent is being pinned.
                pass
        for child_name in child_names:
            try:
                self.state.graph.connect(name, child_name)
            except KeyError:
                # Child is not yet pinned. Skip now; this edge will be
                # connected when the child is being pinned.
                pass

    def _pin_criteria(self):
        criterion_names = [name for name, _ in sorted(
            self._criteria.items(),
            key=self._get_criterion_item_preference,
        )]
        for name in criterion_names:
            # Any pin may modify any criterion during the loop. Criteria are
            # replaced, not updated in-place, so we need to read this value
            # in the loop instead of outside. (sarugaku/resolvelib#5)
            criterion = self._criteria[name]

            if self._is_current_pin_satisfying(name, criterion):
                # If the current pin already works, just use it.
                continue
            candidates = list(criterion.candidates)
            while candidates:
                candidate = candidates.pop()
                dependencies = self._p.get_dependencies(candidate)
                child_names = self._check_pinnability(candidate, dependencies)
                if child_names is None:
                    continue
                self._pin_candidate(name, criterion, candidate, child_names)
                break
            else:   # All candidates tried, nothing works. Give up. (?)
                raise ResolutionImpossible(list(criterion.iter_requirement()))

    def resolve(self, requirements, max_rounds):
        if self._states:
            raise RuntimeError('already resolved')

        for requirement in requirements:
            try:
                name = self._p.identify(requirement)
                self._contribute_to_criteria(name, requirement, parent=None)
            except RequirementsConflicted as e:
                # If initial requirements conflict, nothing would ever work.
                raise ResolutionImpossible(e.requirements + [requirement])

        last = None
        self._r.starting()

        for round_index in range(max_rounds):
            self._r.starting_round(round_index)

            self._push_new_state()
            self._pin_criteria()

            curr = self.state
            if last is not None and len(curr.mapping) == len(last.mapping):
                # Nothing new added. Done! Remove the duplicated entry.
                del self._states[-1]
                self._r.ending(last)
                return
            last = curr

            self._r.ending_round(round_index, curr)

        raise ResolutionTooDeep(max_rounds)


class Resolver(object):
    """The thing that performs the actual resolution work.
    """
    def __init__(self, provider, reporter):
        self.provider = provider
        self.reporter = reporter

    def resolve(self, requirements, max_rounds=20):
        """Take a collection of constraints, spit out the resolution result.

        The return value is a representation to the final resolution result. It
        is a tuple subclass with two public members:

        * `mapping`: A dict of resolved candidates. Each key is an identifier
            of a requirement (as returned by the provider's `identify` method),
            and the value is the resolved candidate.
        * `graph`: A `DirectedGraph` instance representing the dependency tree.
            The vertices are keys of `mapping`, and each edge represents *why*
            a particular package is included. A special vertex `None` is
            included to represent parents of user-supplied requirements.

        The following exceptions may be raised if a resolution cannot be found:

        * `NoVersionsAvailable`: A requirement has no available candidates.
        * `ResolutionImpossible`: A resolution cannot be found for the given
            combination of requirements.
        * `ResolutionTooDeep`: The dependency tree is too deeply nested and
            the resolver gave up. This is usually caused by a circular
            dependency, but you can try to resolve this by increasing the
            `max_rounds` argument.
        """
        resolution = Resolution(self.provider, self.reporter)
        resolution.resolve(requirements, max_rounds=max_rounds)
        return resolution.state
