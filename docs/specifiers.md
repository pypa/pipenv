.. _specifiers:

# Specifiers


## Specifying Versions of a Package

You can specify versions of a package using the `Semantic Versioning scheme <https://semver.org/>`_
(i.e. ``major.minor.micro``).

For example, to install requests you can use: ::

    $ pipenv install requests~=1.2

Pipenv will install version ``1.2`` and any minor update, but not ``2.0``.

This will update your ``Pipfile`` to reflect this requirement, automatically.

In general, Pipenv uses the same specifier format as pip. However, note that according to `PEP 440`_ , you can't use versions containing a hyphen or a plus sign.

.. _`PEP 440`: https://www.python.org/dev/peps/pep-0440/

To make inclusive or exclusive version comparisons you can use: ::

    $ pipenv install "requests>=1.4"   # will install a version equal or larger than 1.4.0
    $ pipenv install "requests<=2.13"  # will install a version equal or lower than 2.13.0
    $ pipenv install "requests>2.19"   # will install 2.19.1 but not 2.19.0

.. note:: The use of double quotes around the package and version specification (i.e. ``"requests>2.19"``) is highly recommended
    to avoid issues with `Input and output redirection <https://robots.thoughtbot.com/input-output-redirection-in-the-shell>`_
    in Unix-based operating systems.

The use of ``~=`` is preferred over the ``==`` identifier as the latter prevents pipenv from updating the packages:  ::

    $ pipenv install "requests~=2.2"  # locks the major version of the package (this is equivalent to using >=2.2, ==2.*)

To avoid installing a specific version you can use the ``!=`` identifier.

For an in depth explanation of the valid identifiers and more complex use cases check `the relevant section of PEP-440`_.

.. _`the relevant section of PEP-440`: https://www.python.org/dev/peps/pep-0440/#version-specifiers

## Specifying Versions of Python

To create a new virtualenv, using a specific version of Python you have installed (and
on your ``PATH``), use the ``--python VERSION`` flag, like so:

Use Python 3::

   $ pipenv --python 3

Use Python3.11::

   $ pipenv --python 3.11


When given a Python version, like this, Pipenv will automatically scan your system for a Python that matches that given version.

If a ``Pipfile`` hasn't been created yet, one will be created for you, that looks like this::

    [[source]]
    url = "https://pypi.python.org/simple"
    verify_ssl = true
    name = "pypi"

    [dev-packages]

    [packages]

    [requires]
    python_version = "3.11"

.. note:: The inclusion of ``[requires] python_version = "3.11"`` specifies that your application requires this version
          of Python, and will be used automatically when running ``pipenv install`` against this ``Pipfile`` in the future
          (e.g. on other machines). If this is not true, feel free to simply remove this section.

If you don't specify a Python version on the command–line, either the ``[requires]`` ``python_full_version`` or ``python_version`` will be selected
automatically, falling back to whatever your system's default ``python`` installation is, at time of execution.


## Editable Dependencies (e.g. ``-e .`` )

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


## VCS Dependencies

VCS dependencies from git and other version control systems using URLs formatted according to the following rule::

    <vcs_type>+<scheme>://<location>/<user_or_organization>/<repository>@<branch_or_tag>#egg=<package_name>

The only optional section is the ``@<branch_or_tag>`` section.  When using git over SSH, you may use the shorthand vcs and scheme alias ``git+git@<location>:<user_or_organization>/<repository>@<branch_or_tag>#egg=<package_name>``. Note that this is translated to ``git+ssh://git@<location>`` when parsed.

Note that it is **strongly recommended** that you install any version-controlled dependencies in editable mode, using ``pipenv install -e``, in order to ensure that dependency resolution can be performed with an up-to-date copy of the repository each time it is performed, and that it includes all known dependencies.

Below is an example usage which installs the git repository located at ``https://github.com/requests/requests.git`` from tag ``v2.20.1`` as package name ``requests``::

    $ pipenv install -e git+https://github.com/requests/requests.git@v2.20.1#egg=requests
    Creating a Pipfile for this project...
    Installing -e git+https://github.com/requests/requests.git@v2.20.1#egg=requests...
    [...snipped...]
    Adding -e git+https://github.com/requests/requests.git@v2.20.1#egg=requests to Pipfile's [packages]...
    [...]

    $ cat Pipfile
    [packages]
    requests = {git = "https://github.com/requests/requests.git", editable = true, ref = "v2.20.1"}

Valid values for ``<vcs_type>`` include ``git``, ``bzr``, ``svn``, and ``hg``.  Valid values for ``<scheme>`` include ``http``, ``https``, ``ssh``, and ``file``.  In specific cases you also have access to other schemes: ``svn`` may be combined with ``svn`` as a scheme, and ``bzr`` can be combined with ``sftp`` and ``lp``.

You can read more about pip's implementation of VCS support `here <https://pip.pypa.io/en/stable/reference/pip_install/#vcs-support>`__. For more information about other options available when specifying VCS dependencies, please check the `Pipfile spec <https://github.com/pypa/pipfile>`_.


## Specifying Package Categories

Originally pipenv supported only two package groups:  ``packages`` and ``dev-packages`` in the ``Pipfile`` which mapped to ``default`` and ``develop`` in the ``Pipfile.lock``.   Support for additional named categories has been added such that arbitrary named groups can utilized across the available pipenv commands.

.. note:: The name will be the same between ``Pipfile`` and lock file, however to support the legacy naming convention it is not possible to have an additional group named ``default`` or ``develop`` in the ``Pipfile``.

By default ``pipenv lock`` will lock all known package categorises; to specify locking only specific groups use the ``--categories`` argument.
The command should process the package groups in the order specified.

Example usages::

	# single category
	pipenv install six --categories prereq

	# multiple categories
	pipenv sync --categories="prereq packages"

	# lock and uninstall examples
	pipenv lock --categories="prereq dev-packages"
	pipenv uninstall six --categories prereq



.. note:: The ``packages``/``default`` specifiers are used to constrain all other categories just as they have done for ``dev-packages``/``develop`` category.  However this is the only way constraints are applied -- the presence of other named groups do not constraint each other, which means it is possible to define conflicting package versions across groups.  This may be desired in some use cases where users only are installing groups specific to their system platform.
