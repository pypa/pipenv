# Contribution Guidelines

Before opening any issues or proposing any pull requests, please do the
following:

1. Read our [Contributor's Guide](https://docs.pipenv.org/dev/contributing/).
2. Understand our [development philosophy](https://docs.pipenv.org/dev/philosophy/).

To get the greatest chance of helpful responses, please also observe the
following additional notes.

## Questions

The GitHub issue tracker is for *bug reports* and *feature requests*. Please do
not use it to ask questions about how to use Pipenv. These questions should
instead be directed to [Stack Overflow](https://stackoverflow.com/). Make sure
that your question is tagged with the `pipenv` tag when asking it on
Stack Overflow, to ensure that it is answered promptly and accurately.

## Good Bug Reports

Please be aware of the following things when filing bug reports:

1. Avoid raising duplicate issues. *Please* use the GitHub issue search feature
   to check whether your bug report or feature request has been mentioned in
   the past. Duplicate bug reports and feature requests are a huge maintenance
   burden on the limited resources of the project. If it is clear from your
   report that you would have struggled to find the original, that's ok, but
   if searching for a selection of words in your issue title would have found
   the duplicate then the issue will likely be closed extremely abruptly.
2. When filing bug reports about exceptions or tracebacks, please include the
   *complete* traceback. Partial tracebacks, or just the exception text, are
   not helpful. Issues that do not contain complete tracebacks may be closed
   without warning.
3. Make sure you provide a suitable amount of information to work with. This
   means you should provide:

   - Guidance on **how to reproduce the issue**. Ideally, this should be a
     *small* code sample that can be run immediately by the maintainers.
     Failing that, let us know what you're doing, how often it happens, what
     environment you're using, etc. Be thorough: it prevents us needing to ask
     further questions.
   - Tell us **what you expected to happen**. When we run your example code,
     what are we expecting to happen? What does "success" look like for your
     code?
   - Tell us **what actually happens**. It's not helpful for you to say "it
     doesn't work" or "it fails". Tell us *how* it fails: do you get an
     exception? A hang? The packages installed seem incorrect?
     How was the actual result different from your expected result?
   - Tell us **what version of Pipenv you're using**, and
     **how you installed it**. Different versions of Pipenv behave
     differently and have different bugs, and some distributors of Pipenv
     ship patches on top of the code we supply.

   If you do not provide all of these things, it will take us much longer to
   fix your problem. If we ask you to clarify these and you never respond, we
   will close your issue without fixing it.

## Development Setup

To get your development environment setup, run:

```sh
pip install -e .
pipenv install --dev
```

This will install the repo version of Pipenv and then install the development
dependencies. Once that has completed, you can start developing.

The repo version of Pipenv must be installed over other global versions to
resolve conflicts with the `pipenv` folder being implicitly added to `sys.path`.
See [pypa/pipenv#2557](https://github.com/pypa/pipenv/issues/2557) for more details.

### Testing

Tests are written in `pytest` style and can be run very simply:

```sh
pytest
```

This will run all Pipenv tests, which can take awhile. To run a subset of the
tests, the standard pytest filters are available, such as:

- provide a directory or file: `pytest tests/unit` or `pytest tests/unit/test_cmdparse.py`
- provide a keyword expression: `pytest -k test_lock_editable_vcs_without_install`
- provide a nodeid: `pytest tests/unit/test_cmdparse.py::test_parse`
- provide a test marker: `pytest -m lock`

#### Package Index

To speed up testing, tests that rely on a package index for locking and
installing use a local server that contains vendored packages in the
`tests/pypi` directory. Each vendored package should have it's own folder
containing the necessary releases. When adding a release for a package, it is
easiest to use either the `.tar.gz` or universal wheels (ex: `py2.py3-none`). If
a `.tar.gz` or universal wheel is not available, add wheels for all available
architectures and platforms.
