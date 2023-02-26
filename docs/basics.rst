.. _basic:

Basic Usage of Pipenv
=====================

.. image:: https://farm4.staticflickr.com/3931/33173826122_b7ee8f1a26_k_d.jpg

This document covers the most basic features of Pipenv.

Pipfile & Pipfile.lock
--------------------------------

``Pipfile`` contains the specification for the project top-level requirements and any desired specifiers.
This file is managed by the developers invoking pipenv commands.
The ``Pipfile`` uses inline tables and the `TOML Spec <https://github.com/toml-lang/toml#user-content-spec>`_.

``Pipfile.lock`` replaces the ``requirements.txt file`` used in most Python projects and adds
security benefits of tracking the packages hashes that were last locked.
This file is managed automatically through locking actions.

You should add both ``Pipfile`` and ``Pipfile.lock`` to the project's source control.

.. _example_files:

Here is a simple example of a ``Pipfile`` and the resulting ``Pipfile.lock``.

Example Pipfile
///////////////

::

    [[source]]
    url = "https://pypi.org/simple"
    verify_ssl = true
    name = "pypi"

    [packages]
    Django = "==4.*"
    waitress = {version = "*", markers="sys_platform == 'win32'"}
    gunicorn = {version = "*", markers="sys_platform == 'linux'"}

    [dev-packages]
    pytest-cov = "==3.*"


Example Pipfile.lock
////////////////////

::

    {
        "_meta": {
            "hash": {
                "sha256": "d09f41c21ecfb3b019ace66b61ea1174f99e8b0da0d39e70a5c1cf2363d8b88d"
            },
            "pipfile-spec": 6,
            "requires": {},
            "sources": [
                {
                    "name": "pypi",
                    "url": "https://pypi.org/simple",
                    "verify_ssl": true
                }
            ]
        },
        "default": {
            "asgiref": {
                "hashes": [
                    "sha256:71e68008da809b957b7ee4b43dbccff33d1b23519fb8344e33f049897077afac",
                    "sha256:9567dfe7bd8d3c8c892227827c41cce860b368104c3431da67a0c5a65a949506"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==3.6.0"
            },
            "django": {
                "hashes": [
                    "sha256:44f714b81c5f190d9d2ddad01a532fe502fa01c4cb8faf1d081f4264ed15dcd8",
                    "sha256:f2f431e75adc40039ace496ad3b9f17227022e8b11566f4b363da44c7e44761e"
                ],
                "index": "pypi",
                "version": "==4.1.7"
            },
            "gunicorn": {
                "hashes": [
                    "sha256:9dcc4547dbb1cb284accfb15ab5667a0e5d1881cc443e0677b4882a4067a807e",
                    "sha256:e0a968b5ba15f8a328fdfd7ab1fcb5af4470c28aaf7e55df02a99bc13138e6e8"
                ],
                "index": "pypi",
                "markers": "sys_platform == 'linux'",
                "version": "==20.1.0"
            },
            "setuptools": {
                "hashes": [
                    "sha256:95f00380ef2ffa41d9bba85d95b27689d923c93dfbafed4aecd7cf988a25e012",
                    "sha256:bb6d8e508de562768f2027902929f8523932fcd1fb784e6d573d2cafac995a48"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==67.3.2"
            },
            "sqlparse": {
                "hashes": [
                    "sha256:0323c0ec29cd52bceabc1b4d9d579e311f3e4961b98d174201d5622a23b85e34",
                    "sha256:69ca804846bb114d2ec380e4360a8a340db83f0ccf3afceeb1404df028f57268"
                ],
                "markers": "python_version >= '3.5'",
                "version": "==0.4.3"
            },
            "waitress": {
                "hashes": [
                    "sha256:7500c9625927c8ec60f54377d590f67b30c8e70ef4b8894214ac6e4cad233d2a",
                    "sha256:780a4082c5fbc0fde6a2fcfe5e26e6efc1e8f425730863c04085769781f51eba"
                ],
                "markers": "sys_platform == 'win32'",
                "version": "==2.1.2"
            }
        },
        "develop": {
            "attrs": {
                "hashes": [
                    "sha256:29e95c7f6778868dbd49170f98f8818f78f3dc5e0e37c0b1f474e3561b240836",
                    "sha256:c9227bfc2f01993c03f68db37d1d15c9690188323c067c641f1a35ca58185f99"
                ],
                "markers": "python_version >= '3.6'",
                "version": "==22.2.0"
            },
            "coverage": {
                "extras": [
                    "toml"
                ],
                "hashes": [
                    "sha256:04481245ef966fbd24ae9b9e537ce899ae584d521dfbe78f89cad003c38ca2ab",
                    "sha256:0c45948f613d5d18c9ec5eaa203ce06a653334cf1bd47c783a12d0dd4fd9c851",
                    "sha256:10188fe543560ec4874f974b5305cd1a8bdcfa885ee00ea3a03733464c4ca265",
                    "sha256:218fe982371ac7387304153ecd51205f14e9d731b34fb0568181abaf7b443ba0",
                    "sha256:29571503c37f2ef2138a306d23e7270687c0efb9cab4bd8038d609b5c2393a3a",
                    "sha256:2a60d6513781e87047c3e630b33b4d1e89f39836dac6e069ffee28c4786715f5",
                    "sha256:2bf1d5f2084c3932b56b962a683074a3692bce7cabd3aa023c987a2a8e7612f6",
                    "sha256:3164d31078fa9efe406e198aecd2a02d32a62fecbdef74f76dad6a46c7e48311",
                    "sha256:32df215215f3af2c1617a55dbdfb403b772d463d54d219985ac7cd3bf124cada",
                    "sha256:33d1ae9d4079e05ac4cc1ef9e20c648f5afabf1a92adfaf2ccf509c50b85717f",
                    "sha256:33ff26d0f6cc3ca8de13d14fde1ff8efe1456b53e3f0273e63cc8b3c84a063d8",
                    "sha256:38da2db80cc505a611938d8624801158e409928b136c8916cd2e203970dde4dc",
                    "sha256:3b155caf3760408d1cb903b21e6a97ad4e2bdad43cbc265e3ce0afb8e0057e73",
                    "sha256:3b946bbcd5a8231383450b195cfb58cb01cbe7f8949f5758566b881df4b33baf",
                    "sha256:3baf5f126f30781b5e93dbefcc8271cb2491647f8283f20ac54d12161dff080e",
                    "sha256:4b14d5e09c656de5038a3f9bfe5228f53439282abcab87317c9f7f1acb280352",
                    "sha256:51b236e764840a6df0661b67e50697aaa0e7d4124ca95e5058fa3d7cbc240b7c",
                    "sha256:63ffd21aa133ff48c4dff7adcc46b7ec8b565491bfc371212122dd999812ea1c",
                    "sha256:6a43c7823cd7427b4ed763aa7fb63901ca8288591323b58c9cd6ec31ad910f3c",
                    "sha256:755e89e32376c850f826c425ece2c35a4fc266c081490eb0a841e7c1cb0d3bda",
                    "sha256:7a726d742816cb3a8973c8c9a97539c734b3a309345236cd533c4883dda05b8d",
                    "sha256:7c7c0d0827e853315c9bbd43c1162c006dd808dbbe297db7ae66cd17b07830f0",
                    "sha256:7ed681b0f8e8bcbbffa58ba26fcf5dbc8f79e7997595bf071ed5430d8c08d6f3",
                    "sha256:7ee5c9bb51695f80878faaa5598040dd6c9e172ddcf490382e8aedb8ec3fec8d",
                    "sha256:8361be1c2c073919500b6601220a6f2f98ea0b6d2fec5014c1d9cfa23dd07038",
                    "sha256:8ae125d1134bf236acba8b83e74c603d1b30e207266121e76484562bc816344c",
                    "sha256:9817733f0d3ea91bea80de0f79ef971ae94f81ca52f9b66500c6a2fea8e4b4f8",
                    "sha256:98b85dd86514d889a2e3dd22ab3c18c9d0019e696478391d86708b805f4ea0fa",
                    "sha256:9ccb092c9ede70b2517a57382a601619d20981f56f440eae7e4d7eaafd1d1d09",
                    "sha256:9d58885215094ab4a86a6aef044e42994a2bd76a446dc59b352622655ba6621b",
                    "sha256:b643cb30821e7570c0aaf54feaf0bfb630b79059f85741843e9dc23f33aaca2c",
                    "sha256:bc7c85a150501286f8b56bd8ed3aa4093f4b88fb68c0843d21ff9656f0009d6a",
                    "sha256:beeb129cacea34490ffd4d6153af70509aa3cda20fdda2ea1a2be870dfec8d52",
                    "sha256:c31b75ae466c053a98bf26843563b3b3517b8f37da4d47b1c582fdc703112bc3",
                    "sha256:c4e4881fa9e9667afcc742f0c244d9364d197490fbc91d12ac3b5de0bf2df146",
                    "sha256:c5b15ed7644ae4bee0ecf74fee95808dcc34ba6ace87e8dfbf5cb0dc20eab45a",
                    "sha256:d12d076582507ea460ea2a89a8c85cb558f83406c8a41dd641d7be9a32e1274f",
                    "sha256:d248cd4a92065a4d4543b8331660121b31c4148dd00a691bfb7a5cdc7483cfa4",
                    "sha256:d47dd659a4ee952e90dc56c97d78132573dc5c7b09d61b416a9deef4ebe01a0c",
                    "sha256:d4a5a5879a939cb84959d86869132b00176197ca561c664fc21478c1eee60d75",
                    "sha256:da9b41d4539eefd408c46725fb76ecba3a50a3367cafb7dea5f250d0653c1040",
                    "sha256:db61a79c07331e88b9a9974815c075fbd812bc9dbc4dc44b366b5368a2936063",
                    "sha256:ddb726cb861c3117a553f940372a495fe1078249ff5f8a5478c0576c7be12050",
                    "sha256:ded59300d6330be27bc6cf0b74b89ada58069ced87c48eaf9344e5e84b0072f7",
                    "sha256:e2617759031dae1bf183c16cef8fcfb3de7617f394c813fa5e8e46e9b82d4222",
                    "sha256:e5cdbb5cafcedea04924568d990e20ce7f1945a1dd54b560f879ee2d57226912",
                    "sha256:ec8e767f13be637d056f7e07e61d089e555f719b387a7070154ad80a0ff31801",
                    "sha256:ef382417db92ba23dfb5864a3fc9be27ea4894e86620d342a116b243ade5d35d",
                    "sha256:f2cba5c6db29ce991029b5e4ac51eb36774458f0a3b8d3137241b32d1bb91f06",
                    "sha256:f5b4198d85a3755d27e64c52f8c95d6333119e49fd001ae5798dac872c95e0f8",
                    "sha256:ffeeb38ee4a80a30a6877c5c4c359e5498eec095878f1581453202bfacc8fbc2"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==7.1.0"
            },
            "iniconfig": {
                "hashes": [
                    "sha256:2d91e135bf72d31a410b17c16da610a82cb55f6b0477d1a902134b24a455b8b3",
                    "sha256:b6a85871a79d2e3b22d2d1b94ac2824226a63c6b741c88f7ae975f18b6778374"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==2.0.0"
            },
            "packaging": {
                "hashes": [
                    "sha256:714ac14496c3e68c99c29b00845f7a2b85f3bb6f1078fd9f72fd20f0570002b2",
                    "sha256:b6ad297f8907de0fa2fe1ccbd26fdaf387f5f47c7275fedf8cce89f99446cf97"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==23.0"
            },
            "pluggy": {
                "hashes": [
                    "sha256:4224373bacce55f955a878bf9cfa763c1e360858e330072059e10bad68531159",
                    "sha256:74134bbf457f031a36d68416e1509f34bd5ccc019f0bcc952c7b909d06b37bd3"
                ],
                "markers": "python_version >= '3.6'",
                "version": "==1.0.0"
            },
            "pytest": {
                "hashes": [
                    "sha256:c7c6ca206e93355074ae32f7403e8ea12163b1163c976fee7d4d84027c162be5",
                    "sha256:d45e0952f3727241918b8fd0f376f5ff6b301cc0777c6f9a556935c92d8a7d42"
                ],
                "markers": "python_version >= '3.7'",
                "version": "==7.2.1"
            },
            "pytest-cov": {
                "hashes": [
                    "sha256:578d5d15ac4a25e5f961c938b85a05b09fdaae9deef3bb6de9a6e766622ca7a6",
                    "sha256:e7f0f5b1617d2210a2cabc266dfe2f4c75a8d32fb89eafb7ad9d06f6d076d470"
                ],
                "index": "pypi",
                "version": "==3.0.0"
            }
        }
    }


General Notes and Recommendations
-------------------------

- Keep both ``Pipfile`` and ``Pipfile.lock`` in version control.
- ``pipenv install`` adds specifiers to ``Pipfile`` and rebuilds the lock file based on the Pipfile specs, by utilizing the internal resolver of ``pip``.
- Not all of the required sub-dependencies need be specified in ``Pipfile``, instead only add specifiers that make sense for the stability of your project.
Example:  ``requests`` requires ``cryptography`` but (for reasons) you want to ensure ``cryptography`` is pinned to a particular version set.
- Consider specifying your target Python version in your ``Pipfile``'s ``[requires]`` section.
For this use either ``python_version`` in the format ``X.Y`` (or ``X``) or ``python_full_version`` in ``X.Y.Z`` format.
- ``pipenv install`` is fully compatible with ``pip install`` package specifiers, for which the full documentation can be found `here <https://pip.pypa.io/en/stable/user_guide/#installing-packages>`__.
- Additional arguments may be supplied to ``pip`` by supplying ``pipenv`` with ``--extra-pip-args``.
- Considering making use of named package categories to further isolate dependency install groups for large monoliths.


☤ Example Pipenv Workflows
-------------------------

Clone / create project repository::

    $ cd myproject

Install from ``Pipfile.lock``, if there is one::

    $ pipenv sync

Add a package to your project, recalibrating entire lock file using the Pipfile specifiers::

    $ pipenv install <package>

Note: This will create a ``Pipfile`` if one doesn't exist. If one does exist, it will automatically be edited with the new package you provided, the lock file updated and the new dependencies installed.

Update everything (equivalent to ``pipenv lock && pipenv sync``::

    $ pipenv update

Update and install just the relevant package and its sub-dependencies::

    $ pipenv update <package>

Update in the Pipfile/lockfile just the relevant package and its sub-dependencies::

    $ pipenv upgrade <package>

Find out what's changed upstream::

    $ pipenv update --outdated

Determine the virtualenv PATH::

    $ pipenv --venv

Activate the Pipenv shell::

    $ pipenv shell

Note: This will spawn a new shell subprocess, which can be deactivated by using ``exit``.


☤ Importing from requirements.txt
---------------------------------

For projects utilizing a ``requirements.txt`` pipenv can import the contents of this file and create a
``Pipfile`` and `Pipfile.lock`` for you::

    $ pipenv install -r path/to/requirements.txt

If your requirements file has version numbers pinned, you'll likely want to edit the new ``Pipfile``
to only keep track of top level dependencies and let ``pipenv`` keep track of pinning sub-dependencies in the lock file.

.. _specifying_versions:

Specifying Versions of a Package
----------------------------------

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


☤ Specifying Package Categories
-------------------------------

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

.. _environment_management:

☤ Environment Management with Pipenv
------------------------------------

.. _pipenv_install:

$ pipenv install
////////////////

``$ pipenv install`` is used for installing packages into the pipenv virtual environment
and updating your Pipfile.

Along with the basic install command, which takes the form::

    $ pipenv install [package names]

The user can provide these additional parameters:

    - ``--python`` — Performs the installation in a virtualenv using the provided Python interpreter.

    .. warning:: None of the above commands should be used together. They are also
                 **destructive** and will delete your current virtualenv before replacing
                 it with an appropriately versioned one.

    - ``--dev`` — Install both ``develop`` and ``default`` packages from ``Pipfile``.
    - ``--system`` — Install packages to the system site-packages rather than into your virtualenv.
    - ``--deploy`` — Verifies the _meta hash of the lock file is up to date with the ``Pipfile``, aborts install if not.
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


☤ Pipfile.lock Security Features
--------------------------------

``Pipfile.lock`` leverages the security of package hash validation in ``pip``.
The ``Pipfile.lock`` is generated with the sha256 hashes of each downloaded package.
This guarantees you're installing the same exact packages on any network as the one
where the lock file was last updated, even on untrusted networks.

We recommend designing CI/CD deployments whereby the build does not alter the lock file as a side effect.
In other words, you can use ``pipenv lock`` or ``pipenv upgrade`` to adjust your lockfile through local development,
the PR process and approve those lock changes before deploying to production that version of the lockfile.
In other words avoid having your CI issue ``lock``, ``update``, ``upgrade`` ``uninstall`` or ``install`` commands that will relock.
Note:  It is counterintuitive that ``pipenv install`` re-locks and ``pipenv sync`` or ``pipenv install --deploy`` does not.
Based on feedback, we may change this behavior of ``pipenv install`` to not re-lock in the future but be mindful of this when designing CI pipelines today.

.. note::

    If you'd like a ``requirements.txt`` output of the lockfile, run ``$ pipenv requirements``.


☤ Pipenv and Docker Containers
------------------------------

In general, you should not have Pipenv inside a linux container image, since
it is a build tool. If you want to use it to build, and install the run time
dependencies for your application, you can use a multistage build for creating
a virtual environment with your dependencies. In this approach,
Pipenv in installed in the base layer, it is then used to create the virtual
environment. In a later stage, in a ``runtime`` layer the virtual environment
is copied from the base layer, the layer containing pipenv and other build
dependencies is discarded.
This results in a smaller image, which can still run your application.
Here is an example ``Dockerfile``, which you can use as a starting point for
doing a multistage build for your application::

  FROM docker.io/python:3.9 AS builder

  RUN pip install --user pipenv

  # Tell pipenv to create venv in the current directory
  ENV PIPENV_VENV_IN_PROJECT=1

  # Pipfile contains requests
  ADD Pipfile.lock Pipfile /usr/src/

  WORKDIR /usr/src

  # NOTE: If you install binary packages required for a python module, you need
  # to install them again in the runtime. For example, if you need to install pycurl
  # you need to have pycurl build dependencies libcurl4-gnutls-dev and libcurl3-gnutls
  # In the runtime container you need only libcurl3-gnutls

  # RUN apt install -y libcurl3-gnutls libcurl4-gnutls-dev

  RUN /root/.local/bin/pipenv sync

  RUN /usr/src/.venv/bin/python -c "import requests; print(requests.__version__)"

  FROM docker.io/python:3.9 AS runtime

  RUN mkdir -v /usr/src/.venv

  COPY --from=builder /usr/src/.venv/ /usr/src/.venv/

  RUN /usr/src/.venv/bin/python -c "import requests; print(requests.__version__)"

  # HERE GOES ANY CODE YOU NEED TO ADD TO CREATE YOUR APPLICATION'S IMAGE
  # For example
  # RUN apt install -y libcurl3-gnutls
  # RUN adduser --uid 123123 coolio
  # ADD run.py /usr/src/

  WORKDIR /usr/src/

  USER coolio

  CMD ["./.venv/bin/python", "-m", "run.py"]

.. Note::

   Pipenv is not meant to run as root. However, in the multistage build above
   it is done nevertheless. A calculated risk, since the intermediate image
   is discarded.
   The runtime image later shows that you should create a user and user it to
   run your application.
   **Once again, you should not run pipenv as root (or Admin on Windows) normally.
   This could lead to breakage of your Python installation, or even your complete
   OS.**

When you build an image with this example (assuming requests is found in Pipfile), you
will see that ``requests`` is installed in the ``runtime`` image::

  $ sudo docker build --no-cache -t oz/123:0.1 .
  Sending build context to Docker daemon  1.122MB
  Step 1/12 : FROM docker.io/python:3.9 AS builder
   ---> 81f391f1a7d7
  Step 2/12 : RUN pip install --user pipenv
   ---> Running in b83ed3c28448
   ... trimmed ...
   ---> 848743eb8c65
  Step 4/12 : ENV PIPENV_VENV_IN_PROJECT=1
   ---> Running in 814e6f5fec5b
  Removing intermediate container 814e6f5fec5b
   ---> 20167b4a13e1
  Step 5/12 : ADD Pipfile.lock Pipfile /usr/src/
   ---> c7632cb3d5bd
  Step 6/12 : WORKDIR /usr/src
   ---> Running in 1d75c6cfce10
  Removing intermediate container 1d75c6cfce10
   ---> 2dcae54cc2e5
  Step 7/12 : RUN /root/.local/bin/pipenv sync
   ---> Running in 1a00b326b1ee
  Creating a virtualenv for this project...
  ... trimmed ...
  ✔ Successfully created virtual environment!
  Virtualenv location: /usr/src/.venv
  Installing dependencies from Pipfile.lock (fe5a22)...
  ... trimmed ...
  Step 8/12 : RUN /usr/src/.venv/bin/python -c "import requests; print(requests.__version__)"
   ---> Running in 3a66e3ce4a11
  2.27.1
  Removing intermediate container 3a66e3ce4a11
   ---> 1db657d0ac17
  Step 9/12 : FROM docker.io/python:3.9 AS runtime
  ... trimmed ...
  Step 12/12 : RUN /usr/src/venv/bin/python -c "import requests; print(requests.__version__)"
   ---> Running in fa39ba4080c5
  2.27.1
  Removing intermediate container fa39ba4080c5
   ---> 2b1c90fd414e
  Successfully built 2b1c90fd414e
  Successfully tagged oz/123:0.1
