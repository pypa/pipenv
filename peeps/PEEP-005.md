# PEEP-005: Use `>=` Specifier in Pipfile by Default

This PEEP proposes changing the default version specifier inserted in Pipfile on `pipenv install <package>` from `*` to use a `>=` based specifier.

☤

## Background

Currently, when the user `pipenv install` a new package, Pipenv inserts an entry in Pipfile without specifying its version requirements. For example:

```
pipenv install django
```

would result in the following Pipfile entry:

```toml
django = "*"
```

It is, however, common for users to want to bound the versions a little. In the case of Django, each new minor version bump (e.g. 2.0 → 2.1) introduces incompatibilities, and applications generally stay on an old, maintained version until the code base is fully migrated. With the current behaviour, the user needs to manually discover down what version is actually being used, and modify the Pipfile entry accordingly.

This PEEP aims to improve the described workflow for people who want to bound package versions, while minimising the liberty provided by the current boundless approach.

## Proposal

When adding a package with `pipenv install`, Pipenv should insert the entry with a `>=` specifier, bounding the package to its latest version (at the time of insertion). The following command run today (2019-03-20)

```
pipenv install django
```

would result in the following Pipfile entry: (2.1.7 being the currently latest version)

```toml
django = ">=2.1.7"
```

This provides an easy way to immediately know what version is installed, and whether it meets with the user’s expectation. If it does not, the entry can still works as a cue, so user knows that 2.1.x is the latest release line.


## Impacts

Pipenv currently goes through the following steps when adding a package via `pipenv install`:

1. Installing the package (with pip)
2. Add the entry to Pipfile (in-memory)
3. Run resolution to update Pipfile.lock, and discover possible incompatibilities
4. Commit the Pipfile change

The first step is unaffected. If the package is already installed, this proposal does not change anything. pip always chooses the latest version when the user does not specify versions, and the proposed `>=` specifier satisfies it.

Step 2 and 4 are changed as described above. They do not have concequences beyond changing the entry itself.

The main impact happens during step 3. The new specifier introduces additional constraints, and may result to new resolution failures. Consider the following situation:

```toml
[packages]
A = "==1.0"
```

* A==1.0 depends on B<2.0
* B has versions 1.0 and 2.0

Previously, the following command

```
pipenv install B
```

would result in a Pipfile.lock of (partial)

```json
{
    "A": {"version": "==1.0"},
    "B": {"version": "==1.0"}
}
```

But with the proposed change, the newly added `B>=2.0` constraint would cause a confliction error instead.

The author thinks this is a helpful approach, and not a deficiency. When users attempt `pipenv install B` without specifiers, they are generally under the impression that the latest version would be installed, since it is how pip works. The current behaviour deviates from this expectation. The author believes that it may result in users assuming either `B==1.0` *is* the latest, or left wondering why Pipenv cannot to find a latest version while pip can.

With the proposed change, the user will be confronted with the message that Pipenv wants to install the latest version, *but fails* because other packages conflicts with it. This would prompt the user to rethink whether the requirement set has potential problems. If the user does intend to use an older version, specifiers can be added accordingly to convey the actual intention, and resolve the problem:

```
pipenv install "B~=1.0"
```

Since a specifier is added, the proposed default specifier would not be added.


## Alternatives

### Pin to “compatible” version

This is mentioned a few times previously, but considered not persuable. Python packaging does not mandate semantic versioning, and therefore does not have a universal idea of compatible versions.

A `>=`-based specifier does not have this problem, since it simply requires versions to be comparable, which Python packaging does guarentee. As mentioned above, the `>=` specifier also serves as partial automation for people who wants to follow semvar. Compared to `*`, it is much easier to write

```toml
django = "~=2.1.0"
``` 

if you already have

```toml
django = ">=2.1.7"
```


----

Author: Tzu-ping Chung <uranusjr@gmail.com>
