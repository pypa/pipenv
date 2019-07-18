# PEEP-006: Pass extra pip arguments on a per-entry basis

This PEEP proposes the introduction of an argument `extra_pip_options` in Pipfile
package entries, which is intended to pass additional options to the invocation of pip.

☤

## Background

Some packages do not install without passing additional arguments to pip,
resulting in failure to lock or install with Pipenv.

As of writing this is the case for most packages that use a `pyproject.toml`
file with `setuptools` in editable mode.
These require pip to be invoked with `--no-use-pep518`.
While it was proposed to solve this by having Pipenv retry with this option,
as soon as the specfic error message (`editable mode is not supported for pyproject.toml-style projects [...] you may pass --no-use-pep517 [...]`) is encountered,
the author proposes the more general solution outlined in the proposal section.
Pip's ability to use environment variables for the names of its option is of no use here.
This is because the environment variable `NO_USE_PEP518` would be applied to **all** pip invocations,
not just the one package, which `setup.py` cannot run correctly without the option.

A less esoteric package for which PEEP-006 would be helpful is `pycurl`.
Here is an excerpt from pycurl's `setup.py`:

```
    def configure_windows(self):
        # Windows users have to pass --curl-dir parameter to specify path
        # to libcurl, because there is no curl-config on windows at all.
        curl_dir = scan_argv(self.argv, "--curl-dir=")
        if curl_dir is None:
            fail("Please specify --curl-dir=/path/to/built/libcurl")
```

The lack of `--curl-dir` does not results in a failure to lock,
since Pipenv cannot retrive the necessary metadata on Windows systems.
This is owned to a failirue running `setup.py`.
Installation is done via wheel and succeeds.

Implementation of PEEP-006 could provide this mandatory option `--curl-dir`
for pycurl, when used in conjunctions with the `platform_system == 'Windows'` marker:

```
[packages]
pycurl = {version = "*", platform_system = "== 'Windows'", extra_pip_options=['--curl-dir=/path/to/curl/config']}
pycurl = {version = "*", platform_system = "!= 'Windows'"}
```

Additionally this woudl give the user fine control over pip to leverage such
options as:

```
$ pip install --help

[...]

  --proxy <proxy>             Specify a proxy in the form
                              [user:passwd@]proxy.server:port.
  --retries <retries>         Maximum number of retries each connection should
                              attempt (default 5 times).
  --timeout <sec>             Set the socket timeout (default 15 seconds).
```

## Proposal

Introduce an extra keyword to a package entry in a Pipfile called `extra_pip_options`.
This keyword shall be of a list type containing pip command line options and their values.

A Pipfile using the new keyword would contain lines similar to these:

```
[packages]
somepack = {version = "*", extra_pip_options=['--no-use-pep518', '--timeout=60', '--retries=20']}
```

The list items would be passed to any invocation of pip just like command
line arguments:

`pip --no-use-pep518 --timeout=60 --retries=20 ...`

Should Pipenv already pass a given argument, the user should get a warning
and the argument Pipenv would use without `extra_pip_options` should be overwritten,
i.e. the one in `extra_pip_options` should be used over its value without `extra_pip_options`.

For some packages it might be useful to support expansion of environment variables:

```
[packages]
pycurl = {version = "*", platform_system = "== 'Windows'", extra_pip_options=['--curl-dir=${CURL_CONFIG_PATH}']}
```

Where `CURL_CONFIG_PATH` would be the variable name of such an environment variable.

----

Author: <con-f-use@gmx.net>
