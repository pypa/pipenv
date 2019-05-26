# PEEP-005: Do Not Remove Entries from the Lockfile When Using `--keep-outdated`

**PROPOSED**

This PEEP describes a change that would retain entries in the Lockfile even if they were not returned during resolution when the user passes the `--keep-outdated` flag.

☤

The `--keep-outdated` flag is currently provided by Pipenv for the purpose of holding back outdated dependencies (i.e. dependencies that are not newly introduced).  This proposal attempts to identify the reasoning behind the flag and identifies a need for a project-wide scoping. Finally, this proposal outlines the expected behavior of `--keep-outdated` under the specified circumstances, as well as the required changes to achieve full implementation.

## Retaining Outdated Dependencies

The purpose of retaining outdated dependencies is to allow the user to introduce a new package to their environment with a minimal impact on their existing environment.  In an effort to achieve this, `keep_outdated` was proposed as both a flag and a Pipfile setting [in this issue](https://github.com/pypa/pipenv/issues/1255#issuecomment-354585775), originally described as follows:

> pipenv lock --keep-outdated to request a minimal update that only adjusts the lock file to account for Pipfile changes (additions, removals, and changes to version constraints)... and pipenv install --keep-outdated needed to request only the minimal changes required to satisfy the installation request

However, the current implementation always fully re-locks, rather than only locking the new dependencies. As a result, dependencies in the `Pipfile.lock` with markers for a python version different from that of the running interpreter will be removed, even if they have nothing to do with the current changeset.  For instance, say you have the following dependency in your `Pipfile.lock`:

```json
{
    "default": {
        "backports.weakref": {
            "hashes": [...],
            "version": "==1.5",
            "markers": "python_version<='3.4'"
        }
    }
}
```

If this lockfile were to be re-generated with Python 3, even with `--keep-outdated`, this entry would be removed.  This makes it very difficult to maintain lockfiles which are compatible across major python versions, yet all that would be required to correct this would be a tweak to the implementation of `keep-outdated`.  I believe this was the goal to begin with, but I feel this behavior should be documented and clarified before moving forward.

## Desired Behavior

1. The only changes that should occur in `Pipfile.lock` when `--keep-outdated` is passed should be changes resulting from new packages added or pin changes in the project `Pipfile`;
2. Existing packages in the project `Pipfile.lock` should remain in place, even if they are not returned during resolution;
3. New dependencies should be written to the lockfile;
4. Conflicts should be resolved as outlined below.

## Conflict Resolution

If a conflict should occur due to the presence in the `Pipfile.lock` of a dependency of a new package, the following steps should be undertaken before alerting the user:

1. Determine whether the previously locked version of the dependency meets the constraints required of the new package; if so, pin that version;
2. If the previously locked version is not present in the `Pipfile` and is not a dependency of any other dependencies (i.e. has no presence in `pipenv graph`, etc), update the lockfile with the new version;
3. If there is a new or existing dependency which has a conflict with existing entries in the lockfile, perform an intermediate resolution step by checking:
    a.  If the new dependency can be satisfied by existing installs;
    b.  Whether conflicts can be upgraded without affecting locked dependencies;
    c.  If locked dependencies must be upgraded, whether those dependencies ultimately have any dependencies in the `Pipfile`;
    d.  If a traversal up the graph lands in the `Pipfile`, create _abstract dependencies_ from the `Pipfile` entries and determine whether they will still be satisfied by the new version;
    e.  If a new pin is required, ensure that any subdependencies of the newly pinned dependencies are therefore also re-pinned (simply prefer the updated lockfile instead of the cached version);

4. Raise an Exception alerting the user that they either need to do a full lock or manually pin a version.

## Necessary Changes

In order to make these changes, we will need to modify the dependency resolution process. Overall, locking will require the following implementation changes:

1. The ability to restore any entries that would otherwise be removed when the `--keep-outdated` flag is passed.  The process already provides a caching mechanism, so we simply need to restore missing cache keys;
2. Conflict resolution steps:
  a. Check an abstract dependency/candidate against a lockfile entry;
  b. Requirements mapping for each dependency in the environment to determine if a lockfile entry is a descendent of any other entries;


Author: Dan Ryan <dan@danryan.co>
