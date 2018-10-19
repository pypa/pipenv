.. _basic:

Basic Usage of Pipenv
=====================

.. image:: https://farm4.staticflickr.com/3931/33173826122_b7ee8f1a26_k_d.jpg

This document covers some of Pipenv's more basic features.

☤ Example Pipfile & Pipfile.lock
--------------------------------

.. _example_files:

Here is a simple example of a ``Pipfile`` and the resulting ``Pipfile.lock``.

Example Pipfile
///////////////

::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true
    name = "pypi"

    [packages]
    requests = "*"


    [dev-packages]
    pytest = "*"


Example Pipfile.lock
////////////////////

::

    {
        "_meta": {
            "hash": {
                "sha256": "8d14434df45e0ef884d6c3f6e8048ba72335637a8631cc44792f52fd20b6f97a"
            },
            "host-environment-markers": {
                "implementation_name": "cpython",
                "implementation_version": "3.6.1",
                "os_name": "posix",
                "platform_machine": "x86_64",
                "platform_python_implementation": "CPython",
                "platform_release": "16.7.0",
                "platform_system": "Darwin",
                "platform_version": "Darwin Kernel Version 16.7.0: Thu Jun 15 17:36:27 PDT 2017; root:xnu-3789.70.16~2/RELEASE_X86_64",
                "python_full_version": "3.6.1",
                "python_version": "3.6",
                "sys_platform": "darwin"
            },
            "pipfile-spec": 5,
            "requires": {},
            "sources": [
                {
                    "name": "pypi",
                    "url": "https://pypi.python.org/simple",
                    "verify_ssl": true
                }
            ]
        },
        "default": {
            "certifi": {
                "hashes": [
                    "sha256:54a07c09c586b0e4c619f02a5e94e36619da8e2b053e20f594348c0611803704",
                    "sha256:40523d2efb60523e113b44602298f0960e900388cf3bb6043f645cf57ea9e3f5"
                ],
                "version": "==2017.7.27.1"
            },
            "chardet": {
                "hashes": [
                    "sha256:fc323ffcaeaed0e0a02bf4d117757b98aed530d9ed4531e3e15460124c106691",
                    "sha256:84ab92ed1c4d4f16916e05906b6b75a6c0fb5db821cc65e70cbd64a3e2a5eaae"
                ],
                "version": "==3.0.4"
            },
            "idna": {
                "hashes": [
                    "sha256:8c7309c718f94b3a625cb648ace320157ad16ff131ae0af362c9f21b80ef6ec4",
                    "sha256:2c6a5de3089009e3da7c5dde64a141dbc8551d5b7f6cf4ed7c2568d0cc520a8f"
                ],
                "version": "==2.6"
            },
            "requests": {
                "hashes": [
                    "sha256:6a1b267aa90cac58ac3a765d067950e7dbbf75b1da07e895d1f594193a40a38b",
                    "sha256:9c443e7324ba5b85070c4a818ade28bfabedf16ea10206da1132edaa6dda237e"
                ],
                "version": "==2.18.4"
            },
            "urllib3": {
                "hashes": [
                    "sha256:06330f386d6e4b195fbfc736b297f58c5a892e4440e54d294d7004e3a9bbea1b",
                    "sha256:cc44da8e1145637334317feebd728bd869a35285b93cbb4cca2577da7e62db4f"
                ],
                "version": "==1.22"
            }
        },
        "develop": {
            "py": {
                "hashes": [
                    "sha256:2ccb79b01769d99115aa600d7eed99f524bf752bba8f041dc1c184853514655a",
                    "sha256:0f2d585d22050e90c7d293b6451c83db097df77871974d90efd5a30dc12fcde3"
                ],
                "version": "==1.4.34"
            },
            "pytest": {
                "hashes": [
                    "sha256:b84f554f8ddc23add65c411bf112b2d88e2489fd45f753b1cae5936358bdf314",
                    "sha256:f46e49e0340a532764991c498244a60e3a37d7424a532b3ff1a6a7653f1a403a"
                ],
                "version": "==3.2.2"
            }
        }
    }

☤ General Recommendations & Version Control
-------------------------------------------

- Generally, keep both ``Pipfile`` and ``Pipfile.lock`` in version control.
- Do not keep ``Pipfile.lock`` in version control if multiple versions of Python are being targeted.
- Specify your target Python version in your `Pipfile`'s ``[requires]`` section. Ideally, you should only have one target Python version, as this is a deployment tool.
- ``pipenv install`` is fully compatible with ``pip install`` syntax, for which the full documentation can be found `here <https://pip.pypa.io/en/stable/user_guide/#installing-packages>`_.



☤ Example Pipenv Workflow
-------------------------

Clone / create project repository::

    $ cd myproject

Install from Pipfile, if there is one::

    $ pipenv install

Or, add a package to your new project::

    $ pipenv install <package>

This will create a ``Pipfile`` if one doesn't exist. If one does exist, it will automatically be edited with the new package you provided.

Next, activate the Pipenv shell::

    $ pipenv shell
    $ python --version

This will spawn a new shell subprocess, which can be deactivated by using ``exit``.

.. _initialization:

☤ Example Pipenv Upgrade Workflow
---------------------------------

- Find out what's changed upstream: ``$ pipenv update --outdated``.
- Upgrade packages, two options:
    a. Want to upgrade everything? Just do ``$ pipenv update``.
    b. Want to upgrade packages one-at-a-time? ``$ pipenv update <pkg>`` for each outdated package.

☤ Importing from requirements.txt
---------------------------------

If you only have a ``requirements.txt`` file available when running ``pipenv install``,
pipenv will automatically import the contents of this file and create a ``Pipfile`` for you.

You can also specify ``$ pipenv install -r path/to/requirements.txt`` to import a requirements file.

If your requirements file has version numbers pinned, you'll likely want to edit the new ``Pipfile``
to remove those, and let ``pipenv`` keep track of pinning.  If you want to keep the pinned versions
in your ``Pipfile.lock`` for now, run ``pipenv lock --keep-outdated``.  Make sure to
`upgrade <#initialization>`_ soon!

.. _specifying_versions:

☤ Specifying Versions of a Package
----------------------------------

You can specify versions of a package using the `Semantic Versioning scheme <https://semver.org/>`_ 
(i.e. ``major.minor.micro``). 

For example, to install requests you can use: ::

    $ pipenv install requests~=1.2   # equivalent to requests~=1.2.0 

Pipenv will install version ``1.2`` and any minor update, but not ``2.0``.

This will update your ``Pipfile`` to reflect this requirement, automatically.

In general, Pipenv uses the same specifier format as pip. However, note that according to `PEP 440`_ , you can't use versions containing a hyphen or a plus sign.

.. _`PEP 440`: <https://www.python.org/dev/peps/pep-0440/>

To make inclusive or exclusive version comparisons you can use: ::

    $ pipenv install "requests>=1.4"   # will install a version equal or larger than 1.4.0
    $ pipenv install "requests<=2.13"  # will install a version equal or lower than 2.13.0
    $ pipenv install "requests>2.19"   # will install 2.19.1 but not 2.19.0 

.. note:: The use of ``" "`` around the package and version specification is highly recommended 
    to avoid issues with `Input and output redirection <https://robots.thoughtbot.com/input-output-redirection-in-the-shell>`_
    in Unix-based operating systems. 

The use of ``~=`` is preferred over the ``==`` identifier as the former prevents pipenv from updating the packages:  ::

    $ pipenv install "requests~=2.2"  # locks the major version of the package (this is equivalent to using ==2.*)

To avoid installing a specific version you can use the ``!=`` identifier.

For an in depth explanation of the valid identifiers and more complex use cases check `the relevant section of PEP-440`_.

.. _`the relevant section of PEP-440`: https://www.python.org/dev/peps/pep-0440/#version-specifiers>

☤ Specifying Versions of Python
-------------------------------

To create a new virtualenv, using a specific version of Python you have installed (and
on your ``PATH``), use the ``--python VERSION`` flag, like so:

Use Python 3::

   $ pipenv --python 3

Use Python3.6::

   $ pipenv --python 3.6

Use Python 2.7.14::

    $ pipenv --python 2.7.14

When given a Python version, like this, Pipenv will automatically scan your system for a Python that matches that given version.

If a ``Pipfile`` hasn't been created yet, one will be created for you, that looks like this::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true

    [dev-packages]

    [packages]

    [requires]
    python_version = "3.6"

.. note:: The inclusion of ``[requires] python_version = "3.6"`` specifies that your application requires this version
          of Python, and will be used automatically when running ``pipenv install`` against this ``Pipfile`` in the future
          (e.g. on other machines). If this is not true, feel free to simply remove this section.

If you don't specify a Python version on the command–line, either the ``[requires]`` ``python_full_version`` or ``python_version`` will be selected
automatically, falling back to whatever your system's default ``python`` installation is, at time of execution.


☤ Editable Dependencies (e.g. ``-e .`` )
----------------------------------------

You can tell Pipenv to install a path as editable — often this is useful for
the current working directory when working on packages::

    $ pipenv install --dev -e .

    $ cat Pipfile
    ...
    [dev-packages]
    "e1839a8" = {path = ".", editable = true}
    ...

.. note:: All sub-dependencies will get added to the ``Pipfile.lock`` as well. Sub-dependencies are **not** added to the
          ``Pipfile.lock`` if you leave the ``-e`` option out.


.. _environment_management:

☤ Environment Management with Pipenv
------------------------------------

The three primary commands you'll use in managing your pipenv environment are
``$ pipenv install``, ``$ pipenv uninstall``, and ``$ pipenv lock``.

.. _pipenv_install:

$ pipenv install
////////////////

``$ pipenv install`` is used for installing packages into the pipenv virtual environment
and updating your Pipfile.

Along with the basic install command, which takes the form::

    $ pipenv install [package names]

The user can provide these additional parameters:

    - ``--two`` — Performs the installation in a virtualenv using the system ``python2`` link.
    - ``--three`` — Performs the installation in a virtualenv using the system ``python3`` link.
    - ``--python`` — Performs the installation in a virtualenv using the provided Python interpreter.

    .. warning:: None of the above commands should be used together. They are also
                 **destructive** and will delete your current virtualenv before replacing
                 it with an appropriately versioned one.

    .. note:: The virtualenv created by Pipenv may be different from what you were expecting.
              Dangerous characters (i.e. ``$`!*@"`` as well as space, line feed, carriage return,
              and tab) are converted to underscores. Additionally, the full path to the current
              folder is encoded into a "slug value" and appended to ensure the virtualenv name
              is unique.

    - ``--dev`` — Install both ``develop`` and ``default`` packages from ``Pipfile``.
    - ``--system`` — Use the system ``pip`` command rather than the one from your virtualenv.
    - ``--ignore-pipfile`` — Ignore the ``Pipfile`` and install from the ``Pipfile.lock``.
    - ``--skip-lock`` — Ignore the ``Pipfile.lock`` and install from the ``Pipfile``. In addition, do not write out a ``Pipfile.lock`` reflecting changes to the ``Pipfile``.

.. _pipenv_uninstall:

$ pipenv uninstall
//////////////////

``$ pipenv uninstall`` supports all of the parameters in `pipenv install <#pipenv-install>`_,
as well as two additional options, ``--all`` and ``--all-dev``.

    - ``--all`` — This parameter will purge all files from the virtual environment,
      but leave the Pipfile untouched.

    - ``--all-dev`` — This parameter will remove all of the development packages from
      the virtual environment, and remove them from the Pipfile.


.. _pipenv_lock:

$ pipenv lock
/////////////

``$ pipenv lock`` is used to create a ``Pipfile.lock``, which declares **all** dependencies (and sub-dependencies) of your project, their latest available versions, and the current hashes for the downloaded files. This ensures repeatable, and most importantly *deterministic*, builds.

☤ About Shell Configuration
---------------------------

Shells are typically misconfigured for subshell use, so ``$ pipenv shell --fancy`` may produce unexpected results. If this is the case, try ``$ pipenv shell``, which uses "compatibility mode", and will attempt to spawn a subshell despite misconfiguration.

A proper shell configuration only sets environment variables like ``PATH`` during a login session, not during every subshell spawn (as they are typically configured to do). In fish, this looks like this::

    if status --is-login
        set -gx PATH /usr/local/bin $PATH
    end

You should do this for your shell too, in your ``~/.profile`` or ``~/.bashrc`` or wherever appropriate.

.. note:: The shell launched in interactive mode. This means that if your shell reads its configuration from a specific file for interactive mode (e.g. bash by default looks for a ``~/.bashrc`` configuration file for interactive mode), then you'll need to modify (or create) this file.

If you experience issues with ``$ pipenv shell``, just check the ``PIPENV_SHELL`` environment variable, which ``$ pipenv shell`` will use if available. For detail, see :ref:`configuration-with-environment-variables`.

☤ A Note about VCS Dependencies
-------------------------------

You can install packages with pipenv from git and other version control systems using URLs formatted according to the following rule::

    <vcs_type>+<scheme>://<location>/<user_or_organization>/<repository>@<branch_or_tag>#egg=<package_name>

The only optional section is the ``@<branch_or_tag>`` section.  When using git over SSH, you may use the shorthand vcs and scheme alias ``git+git@<location>:<user_or_organization>/<repository>@<branch_or_tag>#<package_name>``. Note that this is translated to ``git+ssh://git@<location>`` when parsed.

Note that it is **strongly recommended** that you install any version-controlled dependencies in editable mode, using ``pipenv install -e``, in order to ensure that dependency resolution can be performed with an up to date copy of the repository each time it is performed, and that it includes all known dependencies.

Below is an example usage which installs the git repository located at ``https://github.com/requests/requests.git`` from tag ``v2.19.1`` as package name ``requests``::

    $ pipenv install -e git+https://github.com/requests/requests.git@v2.19#egg=requests
    Creating a Pipfile for this project...
    Installing -e git+https://github.com/requests/requests.git@v2.19.1#egg=requests...
    [...snipped...]
    Adding -e git+https://github.com/requests/requests.git@v2.19.1#egg=requests to Pipfile's [packages]...
    [...]

    $ cat Pipfile
    [packages]
    requests = {git = "https://github.com/requests/requests.git", editable = true, ref = "2.19.1"}

Valid values for ``<vcs_type>`` include ``git``, ``bzr``, ``svn``, and ``hg``.  Valid values for ``<scheme>`` include ``http``, ``https``, ``ssh``, and ``file``.  In specific cases you also have access to other schemes: ``svn`` may be combined with ``svn`` as a scheme, and ``bzr`` can be combined with ``sftp`` and ``lp``.

You can read more about pip's implementation of VCS support `here <https://pip.pypa.io/en/stable/reference/pip_install/#vcs-support>`_. For more information about other options available when specifying VCS dependencies, please check the `Pipfile spec <https://github.com/pypa/pipfile>`_.


☤ Pipfile.lock Security Features
--------------------------------

``Pipfile.lock`` takes advantage of some great new security improvements in ``pip``.
By default, the ``Pipfile.lock`` will be generated with the sha256 hashes of each downloaded
package. This will allow ``pip`` to guarantee you're installing what you intend to when
on a compromised network, or downloading dependencies from an untrusted PyPI endpoint.

We highly recommend approaching deployments with promoting projects from a development
environment into production. You can use ``pipenv lock`` to compile your dependencies on
your development environment and deploy the compiled ``Pipfile.lock`` to all of your
production environments for reproducible builds.

.. note:

    If you'd like a ``requirements.txt`` output of the lockfile, run ``$ pipenv lock -r``.
    This will include all hashes, however (which is great!). To get a ``requirements.txt``
    without hashes, use ``$ pipenv run pip freeze``.

.. _configuration-with-environment-variables:https://docs.pipenv.org/advanced/#configuration-with-environment-variables
