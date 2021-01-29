# PEEP-007: Accepting pre-releases for specific packages

**PROPOSED**

This PEEP describes a change that would allow installing pre-release packages
selectively.

☤

## Installing pre-releases

The current implementation of Pipenv offers capability to install pre-releases
based on the ``--pre`` flag supplied. Another option is to enable installing
pre-releases in the Pipfile itself:

```toml
[pipenv]
allow_prereleases = true
```

This behavior allows installing packages marked as pre-releases for all the
packages that are considered during the dependency resolution. This behavior
might bring unwanted packages to the resolved stack if user's want to
selectively allow packages for which pre-releases are acceptable.

## Accepting pre-releases for certain packages

This PEEP proposes an option which will selectivelly allow installing
pre-releases only for certain packages. The configuration option can be
supplied to the package entry in the Pipfile, similarly as [specifying package
index to be used for installing the
package](https://pipenv-fork.readthedocs.io/en/latest/advanced.html#specifying-package-indexes):

```toml
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = {version="*", index="pypi", allow_prereleases=true}
```

## References

* [pypa/pipenv#1760](https://github.com/pypa/pipenv/issues/1760)

Authors:

* Gaetan Semet <gaetan@xeberon.net>
* Fridolin Pokorny <fridolin.pokorny@gmail.com>
