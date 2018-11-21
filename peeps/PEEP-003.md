# PEEP-003: Specify pipenv options from configuration file

This PEEP describes an addition that would allow configuring `pipenv` options via configuration file.

☤

The discussion in [#2778](https://github.com/pypa/pipenv/issues/2778#issuecomment-417966352) suggested that a new PEEP needed to be created to address the feature discussed in the github issue.
This is an attempt at a PEEP for that feature.

The feature that is specifically being requested is the ability to specify any `pipenv` invocation options in a project (or directory) specific configuration file.

Of particular intrest is an equivalent of the `PIPENV_VENV_IN_PROJECT` option.

It is this author's uneducated suggestion that an extra option to the `Pipfile` file should be added.

Something along the lines of:

```Pipfile
[[source]]
name = "pypi"
url = "https://pypi.org/simple"
verify_ssl = true

[pipenv]
venv_in_project = true

[dev-packages]

[packages]

[requires]
```

_The author recognizes that `Pipfile` is intended to be used by multiple tools and that adding a `[pipenv]` section is likely not the best all around solution._

Ideally, `pipenv` automatically loads options from a file in the current directory.

### Rationale

This feature is helpful to shorten otherwise long lists of command line options that are likely shared between multiple different invocations of `pipenv` and enables easier "in band" management of configuration options.

A common use case is for instance CI builds.
A simple common build sequence might be:
```bash
pipenv install
pipenv run ...
```

There are a few different ways with the current environemnt variables based system to manage any needed share configurations that all have drawbacks:
  <dl>
    <dt>In the CI build system's configuration</dt>
    <dd>Coupling code to CI's private configuration almost guarantees breaking changes in the future</dd>
    <dt>In a subshell's environment variables</dt>
    <dd>Dependency on a specific (even if standard) shell can cause issues on other environemnts</dd>
    <dt>On every line of execution</dt>
    <dd>Annoyingly verbose scripts</dd>
  </dl>
  
  These concerns only get worse as more build steps or common options are added.
