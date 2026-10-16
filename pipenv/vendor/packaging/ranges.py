# This file is dual licensed under the terms of the Apache License, Version
# 2.0, and the BSD License. See the LICENSE file in the root of this repository
# for complete details.
"""Public :class:`VersionRange` API.

A set-algebra view of the versions accepted by a
:class:`~packaging.specifiers.SpecifierSet`. Ranges support intersection,
union, complement, and difference; membership and filtering match the
originating specifier set; and conversion back to a
:class:`~packaging.specifiers.SpecifierSet` is available where a PEP 440 form
exists.

.. testsetup::

    from pipenv.vendor.packaging.ranges import VersionRange
    from pipenv.vendor.packaging.specifiers import SpecifierSet
    from pipenv.vendor.packaging.version import Version
"""

from __future__ import annotations

import enum
import typing
from typing import (
    TYPE_CHECKING,
    Any,
    TypeVar,
    Union,
)

from ._ranges import (
    FULL_RANGE,
    MIN_VERSION,
    NEG_INF,
    POS_INF,
    BoundaryKind,
    BoundaryVersion,
    LowerBound,
    UpperBound,
    coerce_version,
    filter_by_ranges,
    intersect_ranges,
    least_version_above,
    matches_bounds_only,
    range_is_empty,
    ranges_are_prerelease_only,
    trim_release,
)
from .version import Version

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from ._ranges import Interval
    from .specifiers import SpecifierSet


__all__ = ["VersionRange"]

T = TypeVar("T")
UnparsedVersion = Union[Version, str]
UnparsedVersionVar = TypeVar("UnparsedVersionVar", bound=UnparsedVersion)

#: The most ``!=`` exclusion fragments (``!=V`` points or ``!=P.*`` prefixes)
#: that :meth:`VersionRange.to_specifier_set` will materialize to spell a
#: single gap or run. Every site that expands a version-number-driven chain
#: charges it against this cap, and chains that spell one gap together share
#: it (see :func:`_decompose_dev0_gap` and :func:`_encode_gap`),
#: so no gap ever materializes more than this many exclusions. Past the cap
#: the recovery returns ``None`` rather than emit the unbounded chain a range
#: such as ``==5.* | ==1000000.*`` would otherwise drive.
_MAX_EXCLUSION_RUN = 128


class _SetOp(enum.Enum):
    """The binary set operation ``_combine_literals`` resolves over ``===`` literals."""

    INTERSECTION = enum.auto()
    UNION = enum.auto()
    DIFFERENCE = enum.auto()


def __dir__() -> list[str]:
    return __all__


# Range algebra: intersection and the empty-interval test live in the engine
# (``intersect_ranges`` / ``range_is_empty``); union and complement are only
# needed here, so they live in this module.


def _union_ranges(
    left: Sequence[Interval],
    right: Sequence[Interval],
) -> list[Interval]:
    """Union two sorted, non-overlapping interval lists.

    A linear merge over the two pre-sorted inputs followed by a single
    coalescing pass: adjacent or overlapping intervals collapse so the result
    is itself sorted and non-overlapping.
    """
    if not left:
        return list(right)
    if not right:
        return list(left)

    merged_input: list[Interval] = []
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        if left[left_index][0] <= right[right_index][0]:
            merged_input.append(left[left_index])
            left_index += 1
        else:
            merged_input.append(right[right_index])
            right_index += 1
    merged_input.extend(left[left_index:])
    merged_input.extend(right[right_index:])

    merged: list[Interval] = [merged_input[0]]
    for lower, upper in merged_input[1:]:
        prev_lower, prev_upper = merged[-1]

        if (
            prev_upper.version is None
            or lower.version is None
            or prev_upper.version > lower.version
        ):
            overlaps = True
        elif prev_upper.version == lower.version:
            overlaps = prev_upper.inclusive or lower.inclusive
        else:
            # An ordering gap may still hold no version when the two bounds
            # straddle a synthetic boundary; merge across an empty gap to
            # stay canonical.
            gap_lower = LowerBound(prev_upper.version, not prev_upper.inclusive)
            gap_upper = UpperBound(lower.version, not lower.inclusive)
            overlaps = range_is_empty(gap_lower, gap_upper)

        if overlaps:
            merged[-1] = (prev_lower, max(prev_upper, upper))
        else:
            merged.append((lower, upper))

    return merged


def _complement_ranges(ranges: Sequence[Interval]) -> list[Interval]:
    """Complement a sorted, non-overlapping interval list.

    Yields the gaps between intervals plus a leading gap before the first and
    a trailing gap after the last. Bound inclusivity flips so that
    complement-of-complement round-trips back to the input.
    """
    if not ranges:
        return list(FULL_RANGE)

    result: list[Interval] = []
    prev_upper: UpperBound | None = None

    for lower, upper in ranges:
        if prev_upper is None:
            # Leading gap below the first interval. Every range reaching here is
            # floor-canonical: ``_canonical_floor`` has already folded an
            # inclusive lower at or below ``0.dev0`` into ``-inf``. So a finite
            # first lower always leaves a non-empty gap down to ``-inf``, while a
            # ``-inf`` lower leaves no leading gap at all.
            if lower.version is not None:
                gap_upper = UpperBound(lower.version, not lower.inclusive)
                result.append((NEG_INF, gap_upper))
        else:
            gap_lower = LowerBound(prev_upper.version, not prev_upper.inclusive)
            gap_upper = UpperBound(lower.version, not lower.inclusive)
            # Input intervals are canonical (sorted, disjoint, non-touching),
            # so the gap between two of them always holds at least one version.
            result.append((gap_lower, gap_upper))
        prev_upper = upper

    # The empty-input early return guarantees the loop ran.
    assert prev_upper is not None
    if prev_upper.version is not None:
        gap_lower = LowerBound(prev_upper.version, not prev_upper.inclusive)
        result.append((gap_lower, POS_INF))

    return result


def _canonical_floor(bounds: tuple[Interval, ...]) -> tuple[Interval, ...]:
    """Collapse the PEP 440 floor in a sorted interval list.

    Only the first interval can touch ``0.dev0`` (the minimum version). An
    inclusive lower at or below it admits everything below, the same as
    ``-inf``, so ``>=0.dev0`` becomes the one canonical full range. An
    exclusive upper at or below it leaves the interval empty, so it is dropped.
    """
    if not bounds:
        return bounds

    lower, upper = bounds[0]
    if range_is_empty(NEG_INF, upper):
        return bounds[1:]

    if (
        lower.inclusive
        and isinstance(lower.version, Version)
        and lower.version <= MIN_VERSION
    ):
        return ((NEG_INF, upper), *bounds[1:])

    return bounds


def _predecessor_boundary(version: Version) -> BoundaryVersion | None:
    """The boundary whose least successor is *version*, or ``None``.

    Inverse of :func:`~packaging._ranges.least_version_above`. A plain version
    that is exactly such a successor (``1.0a2.dev0`` sits just above
    ``AFTER_POSTS(1.0a1)``) folds back to that boundary, so ``>=1.0a2.dev0`` and
    ``>1.0a1`` share one form. The proposed boundary is confirmed by
    round-tripping through ``least_version_above``.
    """
    # Only a least successor carries a dev segment, so nothing else can fold.
    if version.dev is None:
        return None

    candidate: BoundaryVersion | None = None
    if version.pre is not None and version.dev == 0 and version.post is None:
        # 1.0a2.dev0 -> AFTER_POSTS(1.0a1)
        kind, number = version.pre
        if number >= 1:
            candidate = BoundaryVersion(
                version.__replace__(pre=(kind, number - 1), dev=None),
                BoundaryKind.AFTER_POSTS,
            )
    elif version.dev >= 1:
        # 1.0.dev3 -> AFTER_LOCALS(1.0.dev2)
        candidate = BoundaryVersion(
            version.__replace__(dev=version.dev - 1), BoundaryKind.AFTER_LOCALS
        )
    elif version.dev == 0 and version.post is not None:
        # 1.0.post1.dev0 -> AFTER_LOCALS(1.0.post0); 1.0.post0.dev0 -> AFTER_LOCALS(1.0)
        base = (
            version.__replace__(post=None, dev=None)
            if version.post == 0
            else version.__replace__(post=version.post - 1, dev=None)
        )
        candidate = BoundaryVersion(base, BoundaryKind.AFTER_LOCALS)

    if candidate is not None and least_version_above(candidate) == version:
        return candidate
    return None


def _canonicalize(bounds: tuple[Interval, ...]) -> tuple[Interval, ...]:
    """Fold least-successor bounds to their boundary form.

    ``>=1.0a2.dev0`` and ``>1.0a1`` denote the same set, so both must reduce to
    one representation for ``==`` and ``hash`` to agree. An inclusive lower or
    exclusive upper sitting on a boundary's least successor becomes that
    boundary; the engine's emptiness check has already dropped the synthetic
    gaps such intervals would otherwise leave.
    """
    result: list[Interval] = []
    for lower, upper in bounds:
        new_lower, new_upper = lower, upper

        if isinstance(lower.version, Version) and lower.inclusive:
            boundary = _predecessor_boundary(lower.version)
            if boundary is not None:
                new_lower = LowerBound(boundary, inclusive=False)

        if isinstance(upper.version, Version) and not upper.inclusive:
            boundary = _predecessor_boundary(upper.version)
            if boundary is not None:
                new_upper = UpperBound(boundary, inclusive=True)

        result.append((new_lower, new_upper))
    return tuple(result)


def _struct_admits(
    bounds: tuple[Interval, ...], admit_arbitrary: bool, literal: str
) -> bool:
    """True when the bounds (plus arbitrary admission) admit ``literal``.

    Skips the explicit admit/reject sets, which the caller layers on top. A
    non-version string matches via ``admit_arbitrary`` only on full bounds;
    on narrower bounds the flag is metadata only.
    """
    parsed = coerce_version(literal)
    if parsed is None:
        return admit_arbitrary and bounds == FULL_RANGE

    return matches_bounds_only(bounds, parsed)


# Repr helpers:


def _bound_version_str(value: BoundaryVersion | Version) -> str:
    """Printout for a bound's inner value, kind-tagged for boundaries."""
    if isinstance(value, BoundaryVersion):
        return f"{value.version}[{value.kind.name}]"
    return str(value)


def _format_lower(bound: LowerBound) -> str:
    if bound.version is None:
        return "(-inf"
    bracket = "[" if bound.inclusive else "("
    return f"{bracket}{_bound_version_str(bound.version)}"


def _format_upper(bound: UpperBound) -> str:
    if bound.version is None:
        return "+inf)"
    bracket = "]" if bound.inclusive else ")"
    return f"{_bound_version_str(bound.version)}{bracket}"


def _format_intervals(intervals: Sequence[Interval]) -> str:
    """Render a sorted interval list as ``lower, upper | lower, upper``."""
    return " | ".join(
        f"{_format_lower(lower)}, {_format_upper(upper)}" for lower, upper in intervals
    )


# ``to_specifier_set`` recovery: encode a range's interval list back into
# specifier fragments. Each helper returns ``None`` when its shape has no
# PEP 440 form. The ``keep_dev0`` argument threaded through is a spelling
# mode, not a pre-release policy: false emits a prerelease-free form (no
# synthetic ``.dev0``, so the recovered range has an empty opt-in region),
# true keeps the ``.dev0`` markers (so the range opts its bounds in).
# ``to_specifier_set`` encodes in both modes and keeps whichever round-trips.
#
# Bound and interval encoding: turn one interval's bounds into fragments.


def _is_dev0_version(version: Version) -> bool:
    """True when version is exactly ``X[.Y]*.dev0`` (the shape ``<X`` makes)."""
    return (
        version.dev == 0
        and version.pre is None
        and version.post is None
        and version.local is None
    )


def _clean_lower(version: Version) -> list[str] | None:
    """A prerelease-free spelling for an inclusive ``[version`` lower, or ``None``.

    Several ``[V`` lowers come from an operator whose own spelling carries no
    synthetic ``.dev0``. Recovering that spelling gives the range an empty opt-in
    region, so it is offered in the prerelease-free spelling mode (see
    :meth:`VersionRange.to_specifier_set`).
    """
    if version.dev != 0 or version.pre is not None or version.local is not None:
        return None

    # ``[B.post(k).dev0`` is the lower ``>B.post(k-1)`` builds (k >= 1).
    if version.post is not None:
        if version.post < 1:
            return None
        return [f">{version.__replace__(post=version.post - 1, dev=None)}"]

    # ``[F.dev0`` is family F's base. The prefix P just below F has
    # ``==P.* == [P.dev0, F.dev0)``, so ``>=P,!=P.*`` lands exactly on ``[F.dev0``.
    family = trim_release(version.release)
    last = family[-1]
    if last < 1:
        return None

    below_release = (*family[:-1], last - 1)
    below = Version.from_parts(epoch=version.epoch, release=below_release)

    # At the epoch-0 floor ``==P.*`` already reaches ``0.dev0``, so the ``>=P``
    # half is redundant: ``[1.dev0, +inf)`` is plain ``!=0.*``.
    if version.epoch == 0 and not any(below_release):
        return [f"!={below}.*"]

    return [f">={below}", f"!={below}.*"]


def _epoch_floor_lower(
    lower: LowerBound, upper: UpperBound
) -> tuple[Version, int, bool] | None:
    """The ``E!0`` family of a lower sitting on an epoch>0 zero-family floor.

    An epoch>0 zero-family base such as ``1!0.dev0`` has no ``>=P,!=P.*`` spelling
    since no version sorts below ``E!0`` within the epoch. While the interval
    stays within ``==E!0.*`` it is that wildcard, trimmed by the upper and with a
    leading ``.dev`` run excluded: an ``AFTER_LOCALS(E!0.dev(k))`` lower drops
    ``E!0.dev0..E!0.dev(k)``, a plain inclusive ``E!0.dev0`` lower drops none.
    Returns the ``E!0`` family, how many leading ``.dev`` releases to exclude, and
    whether the upper sits at the family cap (so ``==E!0.*`` needs no upper), else
    ``None``.
    """
    version = lower.version
    if isinstance(version, BoundaryVersion):
        if version.kind != BoundaryKind.AFTER_LOCALS:
            return None
        version = version.version
        if version.dev is None:
            return None
        excluded_devs = version.dev + 1
    elif isinstance(version, Version) and lower.inclusive:
        # A plain inclusive lower only reaches the floor as ``>=E!0.dev0``;
        # higher ``.dev`` would have canonicalized to an AFTER_LOCALS boundary.
        if version.dev != 0:
            return None
        excluded_devs = 0
    else:
        return None

    # Only the bare ``E!0`` floor of a non-zero epoch qualifies.
    if version.epoch == 0:
        return None
    if version.pre is not None or version.post is not None or version.local is not None:
        return None
    if any(trim_release(version.release)):
        return None

    # ``==E!0.*`` spans ``[E!0.dev0, E!1.dev0)``; it fits only below that cap.
    next_family = Version.from_parts(epoch=version.epoch, release=(1,), dev=0)
    cap = UpperBound(next_family, False)
    if upper > cap:
        return None

    family = Version.from_parts(epoch=version.epoch, release=(0,))
    return family, excluded_devs, upper == cap


def _dev_family_anchor(family: Version) -> list[str] | None:
    """Prerelease-free fragments for ``[family, ..)``, or ``None`` if it has none.

    ``family`` is an ``X.dev0``. The floor gives ``[]`` (every version); a release
    base its ``_clean_lower`` family-floor spelling (``!=0.*`` ...); an ``X.post0``
    base ``>=X,!=X``. A pre-release base has no prerelease-free spelling.
    """
    if family <= MIN_VERSION:
        return []
    clean = _clean_lower(family)
    if clean is not None:
        return clean
    if family.pre is None and family.post == 0:
        base = family.__replace__(post=None, dev=None)
        return [f">={base}", f"!={base}"]
    return None


def _encode_lower(lower: LowerBound, keep_dev0: bool) -> list[str] | None:
    """Encode a lower bound as specifier fragments, or ``None``.

    ``[]`` for ``-inf``. An ``AFTER_POSTS(V)`` lower is ``>V``. An
    ``AFTER_LOCALS(V)`` lower is the set ``[successor, ..)`` and emits ``>=V,!=V``,
    except in the prerelease-free spelling mode (``keep_dev0`` false), where it
    recovers a spelling with no synthetic ``.dev0`` when one exists:
    ``>3.8.post1`` for a post release, or a dev family's anchor plus the dev run
    up to V for a ``.dev`` release.
    """
    lower_version = lower.version
    if lower_version is None:
        return []

    if isinstance(lower_version, BoundaryVersion):
        if lower_version.kind == BoundaryKind.AFTER_POSTS:
            # AFTER_POSTS only ever appears as an exclusive ``>V`` lower.
            return [f">{lower_version.version}"]
        inner = lower_version.version
        if inner <= MIN_VERSION:
            # The ``(-inf, V)`` side was dropped at the floor, so the lone
            # ``(AFTER_LOCALS(0.dev0), +inf)`` interval is exactly ``!=0.dev0``.
            return [f"!={inner}"]
        # An ``(AFTER_LOCALS(V), ..)`` lower is the set ``[successor, ..)``. In
        # the prerelease-free mode, recover a spelling with no synthetic ``.dev0``
        # so the range's opt-in region stays empty.
        if not keep_dev0:
            if inner.dev is not None:
                # A ``.dev`` V makes ``[successor, ..)`` its dev family's
                # prerelease-free anchor minus the finite dev run up to ``V``
                # (e.g. ``>=1.0,!=1.0,!=1.0.post0.dev0``), carrying no synthetic
                # ``.dev0``.
                family = inner.__replace__(dev=0)
                anchor = _dev_family_anchor(family)
                if anchor is not None:
                    if inner.dev + 1 > _MAX_EXCLUSION_RUN:
                        return None
                    run = [
                        f"!={family.__replace__(dev=d)}" for d in range(inner.dev + 1)
                    ]
                    return anchor + run
            else:
                # A ``.post`` release recovers its prerelease-free ``>`` spelling
                # from the successor (``>3.8.post1`` for ``AFTER_LOCALS(3.8.post1)``).
                successor = least_version_above(lower_version)
                clean = _clean_lower(successor) if successor is not None else None
                if clean is not None:
                    return clean
        # Otherwise it is ``[V, ..)`` minus V's local family, i.e. ``>=V,!=V``.
        # The prerelease-free recoveries above have already returned in that mode;
        # a residual ``.dev`` V here opts pre-releases in, so this spelling round
        # trips only for a range whose opt-in region wants it.
        return [f">={inner}", f"!={inner}"]

    if not lower.inclusive:
        return None

    # In the prerelease-free mode a ``.dev0`` lower prefers its clean spelling.
    if not keep_dev0:
        clean = _clean_lower(lower_version)
        if clean is not None:
            return clean
    return [f">={lower_version}"]


def _encode_upper(upper: UpperBound, keep_dev0: bool) -> list[str] | None:
    """Encode an upper bound as specifier fragments, or ``None``.

    ``[]`` for ``+inf``. In the prerelease-free spelling mode (``keep_dev0``
    false) the ``<X`` spelling is used for the ``X.dev0`` upper that ``<X``
    builds; otherwise the synthetic ``.dev0`` is kept so the range opts its
    bounds in.
    """
    upper_version = upper.version
    if upper_version is None:
        return []

    if isinstance(upper_version, BoundaryVersion):
        # A boundary upper is always inclusive (a boundary already sits between
        # versions, so no specifier produces an exclusive one).
        if upper_version.kind == BoundaryKind.AFTER_LOCALS:
            inner = upper_version.version
            if (
                not keep_dev0
                and inner.pre is None
                and inner.post is not None
                and inner.dev is None
            ):
                # ``AFTER_LOCALS(post-release)]`` upper is ``<next-post`` (e.g.
                # ``<3.8.post1`` for ``AFTER_LOCALS(3.8.post0)``), the ``<P``
                # spelling a post-release upper builds, with no ``.dev0``.
                return [f"<{inner.__replace__(post=inner.post + 1)}"]
            return [f"<={inner}"]
        # ``AFTER_POSTS(P)`` sits just below the next pre-release's ``.dev0``
        # (canonicalization of a ``<P.preN.dev0`` upper), so it is ``<`` that
        # least successor. A final-release AFTER_POSTS has no successor or form.
        successor = least_version_above(upper_version)
        if successor is not None:
            return [f"<{successor}"]
        return None

    if not upper.inclusive:
        # ``<X`` builds an exclusive ``X.dev0`` upper (X final or post-release;
        # never pre/local). ``<X`` and ``<X.dev0`` define the same bound but
        # differ in the opt-in they imply, so pick by the spelling mode.
        if (
            upper_version.dev == 0
            and upper_version.pre is None
            and upper_version.local is None
        ):
            if not keep_dev0:
                return [f"<{upper_version.__replace__(dev=None)}"]
            return [f"<{upper_version}"]
        # ``V`` (exclusive) upper, including V's pre-releases.
        return [f"<={upper_version}", f"!={upper_version}"]
    return None


def _detect_equal_wildcard(lower: LowerBound, upper: UpperBound) -> Version | None:
    """If ``[lower, upper)`` is the ``==V.*`` shape, return ``V``."""
    if isinstance(lower.version, BoundaryVersion) or isinstance(
        upper.version, BoundaryVersion
    ):
        return None
    if lower.version is None or upper.version is None:
        return None
    if not lower.inclusive or upper.inclusive:
        return None
    if not (_is_dev0_version(lower.version) and _is_dev0_version(upper.version)):
        return None
    if lower.version.epoch != upper.version.epoch:
        return None

    lower_release = trim_release(lower.version.release)
    upper_release = trim_release(upper.version.release)
    padded_length = max(len(lower_release), len(upper_release))
    assert padded_length > 0
    lower_release += (0,) * (padded_length - len(lower_release))
    upper_release += (0,) * (padded_length - len(upper_release))

    if lower_release[:-1] != upper_release[:-1]:
        return None

    # A genuine ``==V.*`` spans one family: the upper is exactly the next prefix.
    # A wider span like ``[3.8.dev0, 3.14.dev0)`` shares the prefix but is not a
    # single wildcard, so it falls through to the generic ``>=...,<...`` form.
    if upper_release[-1] != lower_release[-1] + 1:
        return None

    return lower.version.__replace__(release=lower_release, dev=None)


def _encode_interval(
    lower: LowerBound, upper: UpperBound, keep_dev0: bool
) -> list[str] | None:
    """Encode one interval as specifier fragments, or ``None``.

    Special-cases the ``==V`` singleton (``[V, AFTER_LOCALS(V)]`` for a plain
    ``V``, and ``[V+local, V+local]`` for a local one) and the ``==V.*`` shape
    so the fragment is one equality rather than a bound pair.
    """
    # ``[V+local, V+local]`` (an inclusive local point) is the singleton ``==V+local``.
    if (
        lower.version is not None
        and upper.version is not None
        and not isinstance(lower.version, BoundaryVersion)
        and not isinstance(upper.version, BoundaryVersion)
        and lower.inclusive
        and upper.inclusive
        and lower.version == upper.version
        and lower.version.local is not None
    ):
        return [f"=={lower.version}"]

    # ``[V, AFTER_LOCALS(V)]`` (V without a local) is the singleton ``==V``,
    # which also matches V's local family: one equality, not ``>=V,<=V``.
    if (
        isinstance(lower.version, Version)
        and lower.inclusive
        and upper.inclusive
        and isinstance(upper.version, BoundaryVersion)
        and upper.version.kind == BoundaryKind.AFTER_LOCALS
        and upper.version.version == lower.version
    ):
        return [f"=={lower.version}"]

    wildcard = _detect_equal_wildcard(lower, upper)
    if wildcard is not None:
        return [f"=={wildcard}.*"]

    # A ``[E!0.dev0`` lower has no prerelease-free ``>=`` spelling; within its own
    # family it is ``==E!0.*`` trimmed by the upper.
    floor = _epoch_floor_lower(lower, upper) if not keep_dev0 else None
    if floor is not None:
        family, excluded_devs, upper_at_cap = floor
        if excluded_devs > _MAX_EXCLUSION_RUN:
            return None
        parts = [f"=={family}.*"]
        parts.extend(f"!={family.__replace__(dev=d)}" for d in range(excluded_devs))

        # ``==E!0.*`` already caps at the next family; add the upper only if tighter.
        if not upper_at_cap:
            upper_parts = _encode_upper(upper, keep_dev0)
            if upper_parts is None:
                return None
            parts.extend(upper_parts)

        return parts

    lower_parts = _encode_lower(lower, keep_dev0)
    if lower_parts is None:
        return None

    upper_parts = _encode_upper(upper, keep_dev0)
    if upper_parts is None:
        return None

    return lower_parts + upper_parts


# Gap encoding: spell the gap between two adjacent intervals as exclusions.


def _detect_not_equal(
    left_upper: UpperBound, right_lower: LowerBound
) -> list[Version] | None:
    """If the gap between two intervals is a ``!=V`` chain, list its points.

    A plain exclusive left upper names the first excluded V directly; an inclusive
    boundary left upper names it via its least successor. Adjacent exclusions
    (``V`` and its immediate successors) share a single gap spanning a contiguous
    dev run, so one gap can name a short chain: ``!=1.0,!=1.0.post0.dev0`` is one
    gap from ``1.0`` up to ``AFTER_LOCALS(1.0.post0.dev0)``.
    """
    if isinstance(left_upper.version, BoundaryVersion):
        # A boundary upper is always inclusive; its least successor is the first
        # excluded V (``None`` for a final AFTER_POSTS, which names no point).
        first = least_version_above(left_upper.version)
        if first is None:
            return None
    elif left_upper.version is None or left_upper.inclusive:
        return None
    else:
        first = left_upper.version

    if not isinstance(right_lower.version, BoundaryVersion):
        if (
            right_lower.version is not None
            and not right_lower.inclusive
            and right_lower.version == first
            and first.local is not None
        ):
            return [first]
        return None

    if right_lower.version.kind != BoundaryKind.AFTER_LOCALS:
        return None

    # The right interval resumes just above the last excluded V and its locals.
    last = right_lower.version.version
    if first == last:
        return [first]

    # Adjacent exclusions: the successor of ``first`` opens a ``.dev`` family and
    # every later point is a higher ``.dev`` in that same family, so the gap is
    # exactly ``first`` plus a contiguous dev run up to ``last``. Any other gap
    # (e.g. ``2.3`` to ``AFTER_LOCALS(2.7)`` from complementing ``>=2.3,<=2.7``)
    # spans a whole interval and fails this test.
    second = least_version_above(BoundaryVersion(first, BoundaryKind.AFTER_LOCALS))
    if (
        second is not None
        and second.dev is not None
        and last.dev is not None
        and last.dev >= second.dev
        and last.__replace__(dev=second.dev) == second
    ):
        # ``first`` and the run spell this gap together, so they share the cap.
        if last.dev - second.dev + 2 > _MAX_EXCLUSION_RUN:
            return None
        run = (second.__replace__(dev=d) for d in range(second.dev, last.dev + 1))
        return [first, *run]
    return None


def _decompose_dev0_gap(
    lower_trim: tuple[int, ...],
    upper_trim: tuple[int, ...],
    epoch: int,
    budget: int = _MAX_EXCLUSION_RUN,
) -> list[Version] | None:
    """Decompose the gap ``[L.dev0, U.dev0)`` into wildcard prefixes.

    ``lower_trim``/``upper_trim`` are trimmed release tuples with
    ``lower_trim < upper_trim`` lexicographically. The chain sweeps at the
    first differing level. The gap is undecomposable when L has trailing
    components below that level (the chain cannot escape L's subtree), or when
    the chain, summed across levels, would exceed ``budget`` prefixes.
    """
    diff = 0
    while (
        diff < len(lower_trim)
        and diff < len(upper_trim)
        and lower_trim[diff] == upper_trim[diff]
    ):
        diff += 1

    if len(lower_trim) > diff + 1:
        return None

    common = lower_trim[:diff]
    lower_val = lower_trim[diff] if len(lower_trim) > diff else 0
    upper_val = upper_trim[diff]

    span = upper_val - lower_val
    if span > budget:
        return None

    fragments = [
        Version.from_parts(epoch=epoch, release=(*common, segment))
        for segment in range(lower_val, upper_val)
    ]

    if len(upper_trim) == diff + 1:
        return fragments

    # Recurse into the next release component, charging at least one to the budget
    # per level (not just the span), so a run of zero-span levels (a release with
    # many trailing components) exhausts the budget and returns None instead of
    # recursing past the interpreter's stack limit.
    tail = _decompose_dev0_gap(
        (*common, upper_val), upper_trim, epoch, budget - max(span, 1)
    )
    if tail is None:
        return None
    return fragments + tail


def _encode_gap(left_upper: UpperBound, right_lower: LowerBound) -> list[str] | None:
    """Encode the gap between two adjacent intervals as ``!=`` fragments.

    A point chain becomes ``!=V`` fragments and a dev0 family span becomes
    ``!=P.*`` prefixes, followed by a leading dev run in the last family when
    the gap ends inside it. Any other gap has no exclusion form and returns
    ``None``.
    """
    # Cheapest first: a plain ``!=V`` chain never pays for the budgeted
    # wildcard sweep below.
    points = _detect_not_equal(left_upper, right_lower)
    if points is not None:
        return [f"!={point}" for point in points]

    # Both wildcard shapes start at an exclusive family base ``L.dev0``.
    left_v = left_upper.version
    if (
        not isinstance(left_v, Version)
        or left_upper.inclusive
        or not _is_dev0_version(left_v)
    ):
        return None

    right_v = right_lower.version
    if isinstance(right_v, Version) and right_lower.inclusive:
        # ``[L.dev0, U.dev0)`` is a pure ``!=P.*`` chain up to U's family.
        upper_dev0 = right_v
        run_length = 0
        budget = _MAX_EXCLUSION_RUN
    elif (
        isinstance(right_v, BoundaryVersion)
        and right_v.kind == BoundaryKind.AFTER_LOCALS
        and not right_lower.inclusive
    ):
        # ``[L.dev0, AFTER_LOCALS(U.dev(k))]`` ends inside U's family: the
        # ``!=P.*`` chain, then the ``U.dev0..U.dev(k)`` run. Both spell the
        # gap together, so they share one ``_MAX_EXCLUSION_RUN`` budget.
        upper = right_v.version
        if upper.dev is None or upper.dev + 1 > _MAX_EXCLUSION_RUN:
            return None
        upper_dev0 = upper.__replace__(dev=0)
        run_length = upper.dev + 1
        budget = _MAX_EXCLUSION_RUN - run_length
    else:
        return None

    # ``U`` must be a plain release base in L's epoch, above L.
    # ``_is_dev0_version`` on ``U.dev0`` rejects any pre/post/local on ``U``.
    if not _is_dev0_version(upper_dev0):
        return None
    if left_v.epoch != upper_dev0.epoch or left_v >= upper_dev0:
        return None

    prefixes = _decompose_dev0_gap(
        trim_release(left_v.release),
        trim_release(upper_dev0.release),
        left_v.epoch,
        budget,
    )
    if prefixes is None:
        return None

    exclusions = [f"!={prefix}.*" for prefix in prefixes]
    exclusions.extend(f"!={upper_dev0.__replace__(dev=d)}" for d in range(run_length))
    return exclusions


def _encode_gaps(bounds: Sequence[Interval]) -> list[str] | None:
    """Encode every between-interval gap as ``!=`` fragments, or ``None``.

    When each gap has an exclusion spelling, the intervals fuse into one
    contiguous span (``==1.* | ==3.*`` is ``!=0.*,!=2.*,<4``): the outer
    interval across all the bounds plus these exclusions. A gap with no
    exclusion spelling makes the bounds a disjoint union, which no single
    set expresses.
    """
    exclusions: list[str] = []

    for index in range(1, len(bounds)):
        gap = _encode_gap(bounds[index - 1][1], bounds[index][0])
        if gap is None:
            return None
        exclusions.extend(gap)

    return exclusions


def _tighten_no_prereleases(bounds: tuple[Interval, ...]) -> tuple[Interval, ...]:
    """Snap the range's final upper out of the pre-release band ``False`` drops.

    An exclusive upper at a final ``V`` admits the versions in ``[V.dev0, V)`` at
    the bounds level, but a ``prereleases=False`` policy filters them all out, so
    it accepts the same releases as ``<V`` (upper at ``V.dev0``). Snapping it lets
    :meth:`VersionRange.to_specifier_set` reach the ``<V`` spelling.

    Only the last interval's upper is snapped, the one that gives a terser outer
    bound. Inner uppers are left alone: snapping one turns its gap to the next
    interval into a ``.dev0`` wildcard gap, which a far-apart neighbour would blow
    up into an unbounded ``!=N.*`` chain. Those shapes recover as ``None`` here,
    the same as under ``None`` / ``True``. The snap is conservative (it skips
    boundary, pre-release, and local uppers); the caller keeps it only when it
    stays release-equivalent, so an unsnapped shape falls back to the exact form.
    """
    lower, upper = bounds[-1]
    version = upper.version
    if (
        isinstance(version, Version)
        and not upper.inclusive
        and not version.is_prerelease
        and version.local is None
    ):
        upper = UpperBound(version.__replace__(dev=0), inclusive=False)
        return (*bounds[:-1], (lower, upper))
    return bounds


class VersionRange:
    """A set of :class:`~packaging.version.Version` values accepted by a
    :class:`~packaging.specifiers.SpecifierSet`.

    Construct via :meth:`~packaging.specifiers.SpecifierSet.to_range`, or with
    the :meth:`full`, :meth:`empty`, and :meth:`singleton` class methods.
    Compose with :meth:`intersection`, :meth:`union`, :meth:`complement`, and
    :meth:`difference` (or the ``&`` / ``|`` / ``~`` / ``-`` operators). Test
    membership with ``in`` or :meth:`contains`, filter an iterable with
    :meth:`filter`, and convert back to a
    :class:`~packaging.specifiers.SpecifierSet` with :meth:`to_specifier_set`.

    The configured pre-release policy of the originating specifier set carries
    onto the range and controls whether pre-releases are admitted under ``in``,
    :meth:`contains`, and :meth:`filter`. With no configured policy,
    :meth:`filter` also admits pre-releases in the autodetected opt-in region
    (the versions a pre-release-naming specifier asked for). Set algebra keeps
    that opt-in scoped to those versions, so unrelated pre-releases are not
    admitted wholesale.

    :meth:`intersection`, :meth:`union`, :meth:`difference`, and the
    :meth:`is_subset` / :meth:`is_superset` / :meth:`is_disjoint` predicates
    require both operands to share the same configured policy.

    >>> r = SpecifierSet(">=1.0,<2.0").to_range()
    >>> "1.5" in r
    True
    >>> "2.0" in r
    False
    >>> SpecifierSet(">=2.0,<1.0").to_range().is_empty
    True

    PEP 440's ``===`` operator matches a candidate string verbatim
    (case-insensitive) rather than a set of versions. Ranges built from
    ``===`` specifiers still support membership, set operations, and conversion
    back to a :class:`~packaging.specifiers.SpecifierSet`; matching follows the
    literal-equality rule. A ``===`` literal that names a pre-release is
    admitted under the default policy by both :meth:`contains` and
    :meth:`filter`, since it was named outright.

    .. versionadded:: 26.3
    """

    __slots__ = (
        "_admit",
        "_admit_arbitrary",
        "_bounds",
        "_pre_region",
        "_prereleases_configured",
        "_reject",
    )

    #: The disjoint, sorted, non-overlapping interval list.
    _bounds: tuple[Interval, ...]

    #: Whether this range matches non-version strings as well as versions.
    #: True only by construction on ``SpecifierSet("")`` / :meth:`full`. The flag
    #: rides set algebra but is inert except at full bounds (see
    #: :meth:`_arbitrary_active`). An intersection or difference that shrinks
    #: the bounds drops it (``full() & ~full()`` is plain empty, and
    #: ``full() - r == full() & ~r``); :meth:`complement` and a union of
    #: empty-bounds operands keep it, so ``~~full() == full()`` and
    #: ``~full() | ~full() == ~full()``. Part of equality, since membership
    #: reads it.
    _admit_arbitrary: bool

    #: Case-folded strings the range admits in addition to its bounds.
    #: ``===wat`` produces ``_admit = {"wat"}``.
    _admit: frozenset[str]

    #: Case-folded strings the range rejects (overrides ``_admit`` and the
    #: bounds). Populated by :meth:`complement` of an admit-bearing range and by
    #: literal resolution in :meth:`_combine_literals`.
    _reject: frozenset[str]

    #: Sorted, disjoint intervals where pre-releases are force-admitted under
    #: the PEP 440 default policy (a ``None`` ``prereleases`` argument and no
    #: configured override). The opt-in flows only from the pre-release-naming
    #: specifiers that built the range. :meth:`_build` clips the region to the
    #: bounds, so it is always a subset of them: an opt-in that overflowed its
    #: own cap cannot ride a later union into versions no specifier asked for.
    #: :meth:`union` and :meth:`intersection` accumulate the operands' clipped
    #: regions and re-clip to the result bounds; :meth:`difference` keeps only
    #: the minuend's; and :meth:`complement` drops it, since an exclusion grants
    #: no opt-in. Equality keys on the clipped region, so it stays a congruence.
    _pre_region: tuple[Interval, ...]

    #: Raw configured pre-release override of the originating specifier set
    #: (an explicit ``True`` / ``False``, else ``None``). When set, :meth:`_build`
    #: forces ``_pre_region`` empty since the policy governs globally.
    #: :meth:`intersection` and :meth:`union` require it to match on both
    #: operands. Part of equality.
    _prereleases_configured: bool | None

    def __new__(cls, *args: object, **kwargs: object) -> VersionRange:  # noqa: PYI034
        raise TypeError(
            "cannot create 'VersionRange' instances directly; use "
            "SpecifierSet.to_range(), VersionRange.full(), "
            "VersionRange.empty(), or VersionRange.singleton() instead"
        )

    @classmethod
    def _build(
        cls,
        bounds: tuple[Interval, ...],
        admit: frozenset[str] = frozenset(),
        reject: frozenset[str] = frozenset(),
        admit_arbitrary: bool = False,
        *,
        pre_region: tuple[Interval, ...] = (),
        prereleases_configured: bool | None = None,
    ) -> VersionRange:
        """Internal factory; bypasses :meth:`__new__`.

        Canonicalizes the bounds so equal version sets share one representation,
        then drops admit literals the bounds already admit and reject literals
        the bounds do not match anyway. Reject wins over admit on overlap. The
        pre-release policy is set here and never reassigned afterwards;
        ``pre_region`` is canonicalized like the bounds and clipped to them,
        or dropped when a configured policy makes it inert.
        """
        bounds = _canonicalize(bounds)

        if admit and reject:
            admit = admit - reject
        if admit:
            admit = frozenset(
                literal
                for literal in admit
                if not _struct_admits(bounds, admit_arbitrary, literal)
            )
        if reject:
            reject = frozenset(
                literal
                for literal in reject
                if _struct_admits(bounds, admit_arbitrary, literal)
            )

        instance = object.__new__(cls)
        instance._bounds = bounds
        instance._admit = admit
        instance._reject = reject
        instance._admit_arbitrary = admit_arbitrary
        instance._prereleases_configured = prereleases_configured

        # A configured policy makes the region inert, so drop it. Otherwise fold
        # least-successor bounds (_from_specifier_set passes the region unfolded),
        # so ``>1.0a1`` and ``>=1.0a2.dev0`` carry the same region, then clip it
        # to the bounds so the opt-in never reaches past the range's own versions.
        if prereleases_configured is not None or not pre_region:
            instance._pre_region = ()
        else:
            instance._pre_region = tuple(
                intersect_ranges(_canonicalize(pre_region), bounds)
            )

        return instance

    def _has_literals(self) -> bool:
        return bool(self._admit) or bool(self._reject)

    def _arbitrary_active(self) -> bool:
        """True when ``_admit_arbitrary`` actually admits non-version strings.

        The flag rides through set algebra but only fires admission on full
        bounds. Intersection and difference drop it when the bounds shrink, so
        away from full bounds it survives only on empty-bounds ranges, where
        it keeps ``~~full() == full()`` and union idempotent.
        """
        return self._admit_arbitrary and self._bounds == FULL_RANGE

    def _is_plain(self) -> bool:
        """True when membership is decided by ``_bounds`` alone, enabling the
        bounds-only fast paths in :meth:`is_subset` and :meth:`is_disjoint`.
        """
        return (
            not self._has_literals()
            and not self._admit_arbitrary
            and self._prereleases_configured is not False
        )

    def _check_policy_compat(self, other: VersionRange) -> None:
        """Refuse combining ranges with different pre-release policies."""
        if not isinstance(other, VersionRange):
            raise TypeError(f"expected VersionRange, got {type(other).__name__}")
        if self._prereleases_configured != other._prereleases_configured:
            raise ValueError(
                "Cannot combine VersionRange operands with different "
                f"pre-release policies: {self._prereleases_configured!r} "
                f"and {other._prereleases_configured!r}"
            )

    def _merged_region(self, other: VersionRange) -> tuple[Interval, ...]:
        """Union of ``self`` and ``other``'s opt-in regions.

        Used by :meth:`union` and :meth:`intersection`; :meth:`_build` clips the
        merge to the result bounds. A configured operand carries an empty region,
        so it contributes nothing to the merge.
        """
        # Reuse an operand's canonical tuple when only one side has a region;
        # an empty side contributes nothing to the union.
        if not other._pre_region:
            return self._pre_region
        if not self._pre_region:
            return other._pre_region

        # Both sides carry a region; merge them. _build re-canonicalizes and
        # clips, so the plain union is fine here.
        return tuple(_union_ranges(self._pre_region, other._pre_region))

    def _with_policy(
        self, *, pre_region: tuple[Interval, ...], configured: bool | None
    ) -> VersionRange:
        """A structural copy of this range carrying the given pre-release policy."""
        return self._build(
            self._bounds,
            admit=self._admit,
            reject=self._reject,
            admit_arbitrary=self._admit_arbitrary,
            pre_region=pre_region,
            prereleases_configured=configured,
        )

    @classmethod
    def empty(cls, *, prereleases: bool | None = None) -> VersionRange:
        """Return the empty range. No version satisfies it.

        >>> VersionRange.empty().is_empty
        True
        >>> "1.0" in VersionRange.empty()
        False
        """
        return cls._build((), prereleases_configured=prereleases)

    @classmethod
    def full(
        cls, *, admit_arbitrary: bool = True, prereleases: bool | None = None
    ) -> VersionRange:
        """Return the full range. Every PEP 440 version satisfies it.

        ``admit_arbitrary=False`` restricts the range to PEP 440 versions only
        (matching the same versions as ``SpecifierSet(">=0.dev0").to_range()``);
        its complement is :meth:`empty`. The flag propagates through set algebra
        and is part of equality. Default ``True`` so that ``r & full()``
        preserves ``r``'s own flag structurally.

        >>> "1.0" in VersionRange.full()
        True
        >>> "wat" in VersionRange.full()
        True
        >>> "wat" in VersionRange.full(admit_arbitrary=False)
        False
        """
        return cls._build(
            FULL_RANGE,
            admit_arbitrary=admit_arbitrary,
            prereleases_configured=prereleases,
        )

    @classmethod
    def singleton(
        cls, version: Version | str, *, prereleases: bool | None = None
    ) -> VersionRange:
        """Return the strict singleton range ``{version}``.

        Built as the closed interval ``[version, version]`` with strict
        equality. ``Specifier("==V")`` matches ``V+local`` too, so the strict
        singleton is narrower:

        >>> "1.0+local" in VersionRange.singleton("1.0")
        False
        >>> "1.0+local" in SpecifierSet("==1.0").to_range()
        True

        :raises packaging.version.InvalidVersion: if version is a string that
            does not parse as a PEP 440 version.
        """
        if not isinstance(version, Version):
            version = Version(version)

        lower = LowerBound(version, True)
        upper = UpperBound(version, True)

        # Collapse the floor: nothing sorts below ``MIN_VERSION``, so the
        # ``0.dev0`` singleton is ``(-inf, 0.dev0]`` in canonical form.
        return cls._build(
            _canonical_floor(((lower, upper),)),
            prereleases_configured=prereleases,
        )

    def intersection(self, other: VersionRange) -> VersionRange:
        """Range containing exactly the versions in both self and other.

        Both operands must share the same configured pre-release policy;
        otherwise :exc:`ValueError` is raised.

        >>> a = SpecifierSet(">=1.0").to_range()
        >>> b = SpecifierSet("<2.0").to_range()
        >>> a.intersection(b) == SpecifierSet(">=1.0,<2.0").to_range()
        True
        """
        self._check_policy_compat(other)

        configured = self._prereleases_configured
        new_bounds = tuple(intersect_ranges(self._bounds, other._bounds))
        new_region = self._merged_region(other)

        # An empty intersection (e.g. ``full() & ~full()``) is the empty range,
        # so it drops the arbitrary flag, agreeing with difference when the
        # subtrahend consumes the bounds.
        combined_arb = (
            self._admit_arbitrary and other._admit_arbitrary and bool(new_bounds)
        )

        if not self._has_literals() and not other._has_literals():
            return self._build(
                new_bounds,
                admit_arbitrary=combined_arb,
                pre_region=new_region,
                prereleases_configured=configured,
            )

        return self._combine_literals(
            other,
            new_bounds,
            op=_SetOp.INTERSECTION,
            admit_arbitrary=combined_arb,
            pre_region=new_region,
            prereleases_configured=configured,
        )

    def union(self, other: VersionRange) -> VersionRange:
        """Range containing every version in self or other.

        Both operands must share the same configured pre-release policy;
        otherwise :exc:`ValueError` is raised.

        >>> a = VersionRange.singleton("1.0")
        >>> b = VersionRange.singleton("2.0")
        >>> "1.0" in a.union(b) and "2.0" in a.union(b)
        True
        >>> "1.5" in a.union(b)
        False
        """
        self._check_policy_compat(other)

        configured = self._prereleases_configured
        new_bounds = tuple(_union_ranges(self._bounds, other._bounds))
        new_region = self._merged_region(other)

        # An empty-bounds operand (e.g. ``~full()``) carries an inert arbitrary
        # flag only to keep complement an involution; it admits nothing, so it
        # must not revive arbitrary admission as the union re-widens the bounds.
        if new_bounds:
            combined_arb = (self._admit_arbitrary and bool(self._bounds)) or (
                other._admit_arbitrary and bool(other._bounds)
            )
        else:
            # Nothing widened, so keeping the flags keeps ``r | r == r``.
            combined_arb = self._admit_arbitrary or other._admit_arbitrary

        if not self._has_literals() and not other._has_literals():
            return self._build(
                new_bounds,
                admit_arbitrary=combined_arb,
                pre_region=new_region,
                prereleases_configured=configured,
            )

        return self._combine_literals(
            other,
            new_bounds,
            op=_SetOp.UNION,
            admit_arbitrary=combined_arb,
            pre_region=new_region,
            prereleases_configured=configured,
        )

    def complement(self) -> VersionRange:
        """Range containing every version not in self.

        Preserves the configured pre-release policy. On the version set, double
        negation holds for a range with no ``===`` literals (the arbitrary-string
        flag round-trips, so ``~~full() == full()``); for ``===`` ranges
        complement is one-way. The opt-in region is not restored (see below).

        The opt-in region is dropped: a complement is an exclusion, and an
        exclusion expresses no pre-release preference. This is what lets
        ``a & ~b`` shed ``b``'s opt-in, so an excluded ``b`` never force-admits a
        pre-release into the result. Complement stays involutive on the version
        set, but not on the opt-in region: ``~~r`` covers the same versions as
        ``r`` yet force-admits none of its pre-releases.

        >>> r = SpecifierSet(">=1.0").to_range()
        >>> "0.5" in r.complement()
        True
        >>> "1.5" in r.complement()
        False
        >>> r.complement().complement() == r
        True
        """
        # Complement swaps literal admission: what the range rejects, its
        # complement admits.
        return self._build(
            tuple(_complement_ranges(self._bounds)),
            admit=self._reject,
            reject=self._admit,
            admit_arbitrary=self._admit_arbitrary,
            pre_region=(),
            prereleases_configured=self._prereleases_configured,
        )

    def difference(self, other: VersionRange) -> VersionRange:
        """Range containing the versions in self but not in other.

        Matches ``self & ~other`` on the version set and the opt-in region;
        ``other`` acts as a bounds-only exclusion that grants no opt-in. The
        arbitrary-string flag survives only when ``other`` removed no versions:
        a difference that shrinks the bounds forgets it, as ``self & ~other``
        would, so no later widening union can revive it. They still part on
        ``===`` literals, whose complement is one-way: a ``===`` literal stays
        when ``self`` admits it and ``other`` does not. Both operands must
        share the same configured pre-release policy (as :meth:`intersection`
        and :meth:`union` require); otherwise :exc:`ValueError` is raised.
        ``a - empty()`` returns a range equal to ``a``.

        >>> a = SpecifierSet(">=1.0").to_range()
        >>> b = SpecifierSet(">=2.0").to_range()
        >>> "1.5" in a.difference(b)
        True
        >>> "2.0" in a.difference(b)
        False
        >>> a.difference(VersionRange.empty()) == a
        True
        """
        self._check_policy_compat(other)

        # Subtracting a nothing-admitting set is a no-op; return self unchanged.
        if not other._bounds and not other._admit:
            return self

        # Bound complement is two-way, so subtracting other's versions is an
        # intersection with its gaps.
        new_bounds = tuple(
            intersect_ranges(self._bounds, _complement_ranges(other._bounds))
        )

        # Match ``self & ~other`` on the opt-in region: a complement carries no
        # opt-in, so only ``self``'s region survives. ``other`` acts as a
        # bounds-only exclusion. A configured ``self`` keeps no region.
        new_region: tuple[Interval, ...] = ()
        if self._prereleases_configured is None:
            new_region = self._pre_region

        # Keep self's arbitrary admission only when subtracting removed no
        # versions. A difference that shrinks the bounds forgets the flag, as
        # ``self & ~other`` would, so no later widening union can revive an
        # admission neither operand had.
        combined_arb = self._admit_arbitrary and new_bounds == self._bounds

        if not self._has_literals() and not other._has_literals():
            return self._build(
                new_bounds,
                admit_arbitrary=combined_arb,
                pre_region=new_region,
                prereleases_configured=self._prereleases_configured,
            )

        return self._combine_literals(
            other,
            new_bounds,
            op=_SetOp.DIFFERENCE,
            admit_arbitrary=combined_arb,
            pre_region=new_region,
            prereleases_configured=self._prereleases_configured,
        )

    def _combine_literals(
        self,
        other: VersionRange,
        new_bounds: tuple[Interval, ...],
        *,
        op: _SetOp,
        admit_arbitrary: bool,
        pre_region: tuple[Interval, ...],
        prereleases_configured: bool | None,
    ) -> VersionRange:
        """Resolve admit/reject for ``self`` ``op`` ``other`` over their literals."""
        admits: set[str] = set()
        rejects: set[str] = set()

        # Each literal is decided independently of the others.
        for literal in self._admit | self._reject | other._admit | other._reject:
            self_in = self._matches_literal(literal)
            other_in = other._matches_literal(literal)

            if op is _SetOp.INTERSECTION:
                want = self_in and other_in
            elif op is _SetOp.UNION:
                want = self_in or other_in
            else:
                want = self_in and not other_in

            if want:
                admits.add(literal)
            else:
                rejects.add(literal)

        return self._build(
            new_bounds,
            admit=frozenset(admits),
            reject=frozenset(rejects),
            admit_arbitrary=admit_arbitrary,
            pre_region=pre_region,
            prereleases_configured=prereleases_configured,
        )

    def _matches_literal(self, literal: str) -> bool:
        """Whether literal (case-folded) matches this range's predicate."""
        if literal in self._reject:
            return False
        if literal in self._admit:
            return True

        parsed = coerce_version(literal)
        if parsed is None:
            return self._arbitrary_active()
        return matches_bounds_only(self._bounds, parsed)

    def __and__(self, other: object) -> VersionRange:
        """Operator alias for :meth:`intersection`."""
        if not isinstance(other, VersionRange):
            return NotImplemented
        return self.intersection(other)

    def __or__(self, other: object) -> VersionRange:
        """Operator alias for :meth:`union`."""
        if not isinstance(other, VersionRange):
            return NotImplemented
        return self.union(other)

    def __invert__(self) -> VersionRange:
        """Operator alias for :meth:`complement`."""
        return self.complement()

    def __sub__(self, other: object) -> VersionRange:
        """Operator alias for :meth:`difference`."""
        if not isinstance(other, VersionRange):
            return NotImplemented
        return self.difference(other)

    def is_subset(self, other: VersionRange) -> bool:
        """Return whether every member of self is also a member of other.

        On versions and ``===`` literals this is
        ``self.difference(other).is_empty``: subtracting other leaves nothing
        behind. A live arbitrary admission (the flag at full bounds) is only a
        subset of another live one.

        Both operands must share the same configured pre-release policy;
        otherwise :exc:`ValueError` is raised.

        >>> inner = SpecifierSet(">=1.5,<1.8").to_range()
        >>> outer = SpecifierSet(">=1.0,<2.0").to_range()
        >>> inner.is_subset(outer)
        True
        >>> outer.is_subset(inner)
        False
        >>> VersionRange.empty().is_subset(outer)
        True
        """
        self._check_policy_compat(other)

        # A live arbitrary admission has non-version strings as members, which
        # no bounds cover; only another live admission contains them.
        if self._arbitrary_active() and not other._arbitrary_active():
            return False

        # Plain ranges: subset reduces to bounds containment, no algebra needed.
        if self._is_plain() and other._is_plain():
            return not intersect_ranges(self._bounds, _complement_ranges(other._bounds))

        # difference (unlike intersection with the one-way complement) resolves
        # ``===`` literals against both operands, so it stays correct for them.
        return self.difference(other).is_empty

    def is_superset(self, other: VersionRange) -> bool:
        """Return whether every member of other is also a member of self.

        The mirror of :meth:`is_subset`: ``a.is_superset(b)`` is
        ``b.is_subset(a)``.

        Both operands must share the same configured pre-release policy;
        otherwise :exc:`ValueError` is raised.

        >>> outer = SpecifierSet(">=1.0,<2.0").to_range()
        >>> outer.is_superset(SpecifierSet(">=1.5,<1.8").to_range())
        True
        """
        # Type-guards a non-VersionRange other before delegating to is_subset.
        self._check_policy_compat(other)
        return other.is_subset(self)

    def is_disjoint(self, other: VersionRange) -> bool:
        """Return whether self and other share no member.

        Equivalent to ``(self & other).is_empty``.

        Both operands must share the same configured pre-release policy;
        otherwise :exc:`ValueError` is raised.

        >>> a = SpecifierSet(">=1.0,<2.0").to_range()
        >>> a.is_disjoint(SpecifierSet(">=2.0,<3.0").to_range())
        True
        >>> a.is_disjoint(SpecifierSet(">=1.5,<2.5").to_range())
        False
        """
        self._check_policy_compat(other)

        # Plain ranges: disjointness is an empty bounds intersection.
        if self._is_plain() and other._is_plain():
            return not intersect_ranges(self._bounds, other._bounds)
        return self.intersection(other).is_empty

    def _same_releases(self, other: VersionRange) -> bool:
        """Whether self and other admit the same non-pre-release versions.

        Used by :meth:`to_specifier_set` under a ``prereleases=False`` policy,
        where pre-releases are unobservable: the symmetric difference is empty
        exactly when the two ranges accept the same releases. Both operands
        carry that policy, so the difference below reads emptiness through it.
        """
        return self.difference(other).is_empty and other.difference(self).is_empty

    @typing.overload
    def filter(
        self,
        iterable: Iterable[UnparsedVersionVar],
        prereleases: bool | None = None,
        key: None = ...,
    ) -> Iterator[UnparsedVersionVar]: ...

    @typing.overload
    def filter(
        self,
        iterable: Iterable[T],
        prereleases: bool | None = None,
        key: Callable[[T], UnparsedVersion] = ...,
    ) -> Iterator[T]: ...

    def filter(
        self,
        iterable: Iterable[Any],
        prereleases: bool | None = None,
        key: Callable[[Any], Version | str] | None = None,
    ) -> Iterator[Any]:
        """Yield items from iterable whose version falls inside the range.

        With prereleases ``None`` the PEP 440 default applies: pre-releases are
        buffered and only emitted if no final release in iterable is in range,
        except that a pre-release inside the autodetected opt-in region, or named
        outright by a ``===`` literal, is force-admitted in place (as
        ``prereleases=True`` would yield it). A flushed buffer comes after
        every in-place yield, so the output is not version-sorted.

        The signature mirrors
        :meth:`~packaging.specifiers.SpecifierSet.filter`.

        >>> r = SpecifierSet(">=1.0,<2.0").to_range()
        >>> list(r.filter(["0.9", "1.5", "2.0"]))
        ['1.5']
        """
        region: tuple[Interval, ...] = ()
        if prereleases is None:
            # The region applies only under the autodetect default; a configured
            # policy governs instead (and then ``_pre_region`` is already empty).
            prereleases = self._prereleases_configured
            region = self._pre_region

        arbitrary_active = self._arbitrary_active()
        if not self._admit and not self._reject and not arbitrary_active:
            # A region spanning the whole bounds force-admits every in-bounds
            # pre-release, i.e. ``prereleases=True``; take the cheaper no-buffer
            # path. (Confined to this branch: the admission path orders arbitrary
            # strings differently under True than under the region.)
            if region and region == self._bounds:
                return filter_by_ranges(self._bounds, iterable, key, True)
            return filter_by_ranges(self._bounds, iterable, key, prereleases, region)
        return self._filter_with_admission(
            iterable, key, prereleases, arbitrary_active, region
        )

    def _filter_with_admission(
        self,
        iterable: Iterable[Any],
        key: Callable[[Any], Version | str] | None,
        prereleases: bool | None,
        arbitrary_active: bool,
        region: tuple[Interval, ...],
    ) -> Iterator[Any]:
        """Filter for ranges with admit/reject literals or live arbitrary
        admission (including the universal ``SpecifierSet("")`` range)."""
        admit_set = self._admit
        reject_set = self._reject

        def admit(item: Any) -> tuple[bool, Version | None, bool]:  # noqa: ANN401
            raw: Version | str = item if key is None else key(item)
            raw_lower = str(raw).lower()

            if reject_set and raw_lower in reject_set:
                return False, None, False
            if admit_set and raw_lower in admit_set:
                # An explicit ``===`` literal names this version outright.
                return True, coerce_version(raw), True

            parsed = coerce_version(raw)
            if parsed is None:
                return arbitrary_active, None, False
            if not matches_bounds_only(self._bounds, parsed):
                return False, None, False
            return True, parsed, False

        if prereleases is True:
            for item in iterable:
                ok, _, _ = admit(item)
                if ok:
                    yield item
            return

        if prereleases is False:
            for item in iterable:
                ok, parsed, _ = admit(item)
                if not ok:
                    continue
                if parsed is not None and parsed.is_prerelease:
                    continue
                yield item
            return

        # PEP 440 default: emit finals eagerly and buffer the other pre-releases,
        # releasing the buffer only if no final ever matches.
        all_nonfinal: list[Any] = []
        arbitrary_strings: list[Any] = []
        found_final = False

        for item in iterable:
            ok, parsed, by_literal = admit(item)
            if not ok:
                continue

            if parsed is None:
                if found_final:
                    yield item
                else:
                    arbitrary_strings.append(item)
                    all_nonfinal.append(item)
                continue

            if not parsed.is_prerelease:
                if not found_final:
                    yield from arbitrary_strings
                    arbitrary_strings.clear()
                    found_final = True
                yield item
                continue

            # A pre-release is force-admitted when it is named outright by a
            # ``===`` literal or falls in the opt-in region, as ``prereleases=True``
            # would yield it; otherwise the PEP 440 default buffers it.
            if by_literal or (region and matches_bounds_only(region, parsed)):
                yield item
                continue

            if not found_final:
                all_nonfinal.append(item)

        if not found_final:
            yield from all_nonfinal

    @classmethod
    def _from_specifier_set(cls, specifier_set: SpecifierSet) -> VersionRange:
        """Build the range accepted by ``specifier_set``.

        Friend constructor for :meth:`~packaging.specifiers.SpecifierSet.to_range`.
        The intersection of every specifier in the set: an empty set yields the
        full range, an unsatisfiable set yields the empty range, and ``===``
        specifiers contribute literal-string admission.
        """
        if not specifier_set:
            result = cls.full()
        elif not specifier_set._has_arbitrary:
            result = cls._build(
                bounds=_canonical_floor(tuple(specifier_set._get_ranges()))
            )
        else:
            result = cls.full()
            for spec in specifier_set:
                if spec.operator == "===":
                    operand = cls._build(
                        bounds=(), admit=frozenset({spec.version.lower()})
                    )
                else:
                    operand = cls._build(
                        bounds=_canonical_floor(tuple(spec._to_ranges()))
                    )
                result = result.intersection(operand)

        # Each pre-release-naming specifier opts its own versions in; their union,
        # clipped to the set's bounds by _build, is the region. Clipping refolds
        # under intersection, so a set built directly equals one built by
        # intersecting its specifiers one at a time.
        region: list[Interval] = []
        if specifier_set._prereleases is None:  # a configured policy has no region
            for spec in specifier_set:
                # ``===`` literals are not a range; filter force-admits them.
                if spec.operator != "===" and spec.prereleases:
                    spec_bounds = _canonical_floor(tuple(spec._to_ranges()))
                    region = _union_ranges(region, spec_bounds)

        return result._with_policy(
            pre_region=tuple(region),
            configured=specifier_set._prereleases,
        )

    def to_specifier_set(self) -> SpecifierSet | None:
        """Return a :class:`~packaging.specifiers.SpecifierSet` matching the same
        versions as self, or ``None`` if no single set expresses it.

        PEP 440 has no syntax for the strict singleton ``{V}`` (an exclusive
        plain-version bound), a disjoint union of two or more intervals, or a
        partial pre-release opt-in region, so ranges built by set algebra often
        return ``None``. A gap that takes more than ``_MAX_EXCLUSION_RUN``
        contiguous ``!=`` exclusions to spell returns ``None`` too,
        rather than a pathologically long chain; reaching that cap takes either
        set algebra or a specifier set that already spells the gap out with
        over a hundred contiguous ``!=N.*`` exclusions. An empty range maps to
        ``SpecifierSet("<0")``, unless it still carries the arbitrary-string
        flag (which no set reproduces), and a full range that admits arbitrary
        strings maps to ``SpecifierSet("")``.

        A range built from a :class:`~packaging.specifiers.SpecifierSet`
        re-encodes, short of that exclusion cap. The result is the simplest
        candidate whose own
        :meth:`~packaging.specifiers.SpecifierSet.to_range` reproduces self
        exactly (bounds, ``===`` literals, and the opt-in region are all part of
        equality), so it filters the same versions. Two cases relax that
        exactness without changing what is filtered: an empty range recovers as
        the canonical empty range (same versions, none, but not self's bounds),
        and under a ``prereleases=False`` policy the result need only match self's
        releases, so ``(-inf, 3.14)`` recovers as the tighter ``<3.14`` rather
        than ``!=3.14,<=3.14``.

        Each call encodes a handful of candidate spellings and keeps the
        simplest one that verifies, where verifying means parsing the candidate
        and round-tripping it through
        :meth:`~packaging.specifiers.SpecifierSet.to_range`. The work grows
        with the number of intervals and exclusions in the range, and the
        result is not cached, so convert once and reuse the returned set rather
        than converting per candidate version in a hot loop.

        >>> str(SpecifierSet(">=1.0,<2.0").to_range().to_specifier_set())
        '<2.0,>=1.0'
        >>> str(SpecifierSet("==1.0").to_range().to_specifier_set())
        '==1.0'
        >>> VersionRange.singleton("1.5").to_specifier_set() is None
        True
        """
        from .specifiers import InvalidSpecifier, SpecifierSet  # noqa: PLC0415

        configured = self._prereleases_configured

        if self._reject:
            return None
        if self._admit_arbitrary and self._bounds != FULL_RANGE:
            return None
        if self.is_empty:
            # Every member-free spelling accepts the same versions (none), so the
            # canonical ``<0`` stands in for all of them; a configured policy
            # rides along it.
            return SpecifierSet("<0", prereleases=configured)

        if not self._bounds:
            # Pure ``===`` literals; only a single literal has a single-set form.
            if len(self._admit) != 1:
                return None
            (literal,) = self._admit
            bases = [f"==={literal}"]
        elif self._admit:
            # Bounds plus literals cannot be one set.
            return None
        elif self._bounds == FULL_RANGE:
            bases = ["" if self._admit_arbitrary else ">=0.dev0"]
        else:
            # Under ``prereleases=False`` an exclusive final upper admits the same
            # releases as ``<V`` (the ``[V.dev0, V)`` band is excluded), so offer
            # the tightened bounds as well; a tightening that is not
            # release-equivalent is dropped by the acceptance check below.
            layouts = [self._bounds]
            if configured is False:
                tightened = _tighten_no_prereleases(self._bounds)
                if tightened != self._bounds:
                    layouts.append(tightened)

            # Encode each layout in both spelling modes: prerelease-free, then
            # keeping the synthetic ``.dev0`` markers. Which spelling reproduces
            # self is settled by the round trip below, not up front. The gap
            # exclusions do not depend on the mode, so they encode once.
            bases = []
            for layout in layouts:
                exclusions = _encode_gaps(layout)
                if exclusions is None:
                    continue

                for keep_dev0 in (False, True):
                    outer = _encode_interval(layout[0][0], layout[-1][1], keep_dev0)
                    if outer is None:
                        continue
                    base = ",".join(outer + exclusions)
                    if base not in bases:
                        bases.append(base)

        # A trailing no-op ``>=0.dev0`` floor restores a ``True`` opt-in that
        # rode on a floor the clean encoding dropped (e.g. ``>=0.dev0,!=1.0``).
        # It always recovers the whole bounds as the opt-in region, so it can
        # only round-trip when self opts everything in.
        add_floor = configured is None and self._pre_region == self._bounds

        # Keep the simplest candidate that recovers self. ``==`` compares bounds,
        # literals, and the opt-in region, so a candidate that would filter
        # differently, or an op-built range with no single-set form, is rejected
        # below. Under ``prereleases=False`` a candidate need only match self's
        # releases (policies never mix, so the excluded pre-releases are
        # unobservable), which admits the tightened spellings above.
        best: SpecifierSet | None = None
        best_key = (0, 0)

        for base in bases:
            candidates = [base]
            if add_floor:
                candidates.append(f"{base},>=0.dev0" if base else ">=0.dev0")

            for spec_str in candidates:
                # A ``===`` literal can hold a comma (its arbitrary version
                # excludes only whitespace, ``;`` and ``)``), which the set
                # string splits on. Such a literal has no single specifier-set
                # spelling, so drop the unparsable candidate and let the range
                # fall through to ``None`` rather than raise.
                try:
                    recovered = SpecifierSet(spec_str, prereleases=configured)
                except InvalidSpecifier:
                    continue
                # Fewest fragments, then shortest string. Rank before the round
                # trip so a candidate that cannot beat the best skips the check
                # (its ``==`` and, under ``False``, two ``difference`` calls).
                key = (len(recovered), len(str(recovered)))
                if best is not None and key >= best_key:
                    continue

                # Accept an exact round trip, or (under ``False``) one that only
                # matches the releases the policy leaves observable.
                candidate = recovered.to_range()
                matches = candidate == self or (
                    configured is False and self._same_releases(candidate)
                )
                if matches:
                    best, best_key = recovered, key

        return best

    @property
    def is_empty(self) -> bool:
        """``True`` if no version or string satisfies this range.

        Agrees with :meth:`~packaging.specifiers.SpecifierSet.is_unsatisfiable`,
        including the pre-release policy: a range whose only members are
        pre-releases is empty when that policy excludes them.

        >>> SpecifierSet(">=2,<1").to_range().is_empty
        True
        >>> SpecifierSet(">=1,<2").to_range().is_empty
        False
        >>> SpecifierSet("==1.0a1", prereleases=False).to_range().is_empty
        True
        """
        # An arbitrary-string admission or a surviving ``===`` literal is a
        # member; a literal that is a pre-release is dropped when the policy is.
        if self._arbitrary_active():
            return False

        excludes_prereleases = self._prereleases_configured is False
        for literal in self._admit:
            if excludes_prereleases:
                parsed = coerce_version(literal)
                if parsed is not None and parsed.is_prerelease:
                    continue
            return False

        if not self._bounds:
            return True

        return excludes_prereleases and ranges_are_prerelease_only(self._bounds)

    def contains(
        self,
        item: Version | str,
        prereleases: bool | None = None,
        installed: bool | None = None,
    ) -> bool:
        """Return whether item is contained in this range.

        :param item: a version string or :class:`~packaging.version.Version`.
        :param prereleases: whether to match pre-releases. ``None`` (default)
            uses the range's own policy.
        :param installed: when ``True``, accept a pre-release item even if the
            range would not otherwise allow it.

        Unlike :meth:`filter`, this does not consult the autodetected pre-release
        opt-in region; it reads only the configured policy. This mirrors
        :meth:`~packaging.specifiers.SpecifierSet.contains` versus
        :meth:`~packaging.specifiers.SpecifierSet.filter`.

        Unparsable strings do not match, except where the full
        ``SpecifierSet`` would also match: the full range admits any string,
        and a ``===`` range admits items equal to the literal
        case-insensitively.

        >>> r = SpecifierSet(">=1.0,<2.0").to_range()
        >>> r.contains("1.5")
        True
        >>> r.contains("2.0")
        False

        :raises TypeError: if item is not a str or Version.
        """
        if not isinstance(item, (str, Version)):
            raise TypeError(
                f"VersionRange.contains() expected str or Version, "
                f"got {type(item).__name__}"
            )

        parsed: Version | None = item if isinstance(item, Version) else None
        if installed and parsed is None:
            parsed = coerce_version(item)
        if installed and parsed is not None and parsed.is_prerelease:
            prereleases = True

        effective_pre = (
            self._prereleases_configured if prereleases is None else prereleases
        )

        if self._admit or self._reject:
            item_str = str(item).lower()
            if item_str in self._reject:
                return False
            if item_str in self._admit:
                if effective_pre is False:
                    literal_parsed = coerce_version(item_str)
                    if literal_parsed is not None and literal_parsed.is_prerelease:
                        return False
                return True

        if not isinstance(item, Version):
            if parsed is None:
                parsed = coerce_version(item)
            if parsed is None:
                return self._arbitrary_active()
            item = parsed

        if effective_pre is False and item.is_prerelease:
            return False
        return matches_bounds_only(self._bounds, item)

    def __contains__(self, item: Version | str) -> bool:
        """Return whether item is contained in this range.

        Forwards to :meth:`contains` with default arguments.

        >>> "1.5" in SpecifierSet(">=1.0,<2.0").to_range()
        True
        """
        return self.contains(item)

    def __eq__(self, other: object) -> bool:
        """Structural equality.

        Compares the bounds, the ``===`` admit/reject literals, the
        arbitrary-string flag, the configured pre-release policy, and the
        opt-in region, not just the version set. Keying on the region makes
        equality a congruence (equal ranges stay equal under further operations),
        so equal implies same :meth:`contains` and :meth:`filter`, but not the
        converse: an empty range keeps the flag it was built with, so two empty
        ranges need not be equal.

        Different specifiers for the same range fold to one canonical form:

        >>> SpecifierSet(">1.0a1").to_range() == SpecifierSet(">=1.0a2.dev0").to_range()
        True

        The opt-in region is part of equality, so ``<=1.0`` (no pre-releases) and
        ``<1.0.post0.dev0`` (autodetects a ``.dev`` opt-in) cover the same
        versions yet compare unequal:

        >>> le, lt = SpecifierSet("<=1.0"), SpecifierSet("<1.0.post0.dev0")
        >>> le.to_range() == lt.to_range()
        False

        >>> r = SpecifierSet(">=1.0,<2.0").to_range()
        >>> r == SpecifierSet(">=1.0,<2.0").to_range()
        True
        """
        if not isinstance(other, VersionRange):
            return NotImplemented
        return (
            self._bounds == other._bounds
            and self._admit == other._admit
            and self._reject == other._reject
            and self._admit_arbitrary == other._admit_arbitrary
            and self._prereleases_configured == other._prereleases_configured
            and self._pre_region == other._pre_region
        )

    def __hash__(self) -> int:
        return hash(
            (
                self._bounds,
                self._admit,
                self._reject,
                self._admit_arbitrary,
                self._prereleases_configured,
                self._pre_region,
            )
        )

    def __repr__(self) -> str:
        """Human-readable representation for debugging.

        >>> SpecifierSet(">=1.0,<2.0").to_range()
        <VersionRange '[1.0, 2.0.dev0)'>
        >>> SpecifierSet("").to_range()
        <VersionRange '(-inf, +inf)' arbitrary>
        >>> SpecifierSet(">=2.0,<1.0").to_range()
        <VersionRange '(empty)'>
        """
        # Body: the bounds and any ``===``-admitted literals.
        parts: list[str] = []
        if self._bounds:
            parts.append(_format_intervals(self._bounds))
        if self._admit:
            parts.append("{" + ", ".join(sorted(self._admit)) + "}")
        body = " | ".join(parts) if parts else "(empty)"

        # Rejected literals subtract from the body.
        if self._reject:
            body = f"{body} \\ {{{', '.join(sorted(self._reject))}}}"

        # Tail: the policy flags carried alongside the version set.
        tail = ""
        if self._admit_arbitrary:
            tail += " arbitrary"
        if self._prereleases_configured is not None:
            tail += f" pre={self._prereleases_configured}"
        if self._pre_region:
            tail += f" pre-region={_format_intervals(self._pre_region)!r}"

        return f"<{self.__class__.__name__} {body!r}{tail}>"
