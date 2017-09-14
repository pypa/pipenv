Policy
======

* Vendored libraries **MUST** not be modified except as required to
  successfully vendor them.

* Vendored libraries **MUST** be released copies of libraries available on
  PyPI.

* The versions of libraries vendored in pip **MUST** be reflected in
  ``pip/_vendor/vendor.txt``.

* Vendored libraries **MUST** function without any build steps such as 2to3 or
  compilation of C code, pratically this limits to single source 2.x/3.x and
  pure Python.

* Any modifications made to libraries **MUST** be noted in
  ``pip/_vendor/README.rst``.


Rationale
---------

Historically pip has not had any dependencies except for setuptools itself,
choosing instead to implement any functionality it needed to prevent needing
a dependency. However, starting with pip 1.5 we began to replace code that was
implemented inside of pip with reusable libraries from PyPI. This brought the
typical benefits of reusing libraries instead of reinventing the wheel like
higher quality and more battle tested code, centralization of bug fixes
(particularly security sensitive ones), and better/more features for less work.

However, there is several issues with having dependencies in the traditional
way (via ``install_requires``) for pip. These issues are:

* Fragility. When pip depends on another library to function then if for
  whatever reason that library either isn't installed or an incompatible
  version is installed then pip ceases to function. This is of course true for
  all Python applications, however for every application *except* for pip the
  way you fix it is by re-running pip. Obviously when pip can't run you can't
  use pip to fix pip so you're left having to manually resolve dependencies and
  installing them by hand.

* Making other libraries uninstallable. One of pip's current dependencies is
  the requests library, for which pip requires a fairly recent version to run.
  If pip dependended on requests in the traditional manner then we'd end up
  needing to either maintain compatibility with every version of requests that
  has ever existed (and will ever exist) or some subset of the versions of
  requests available will simply become uninstallable depending on what version
  of pip you're using. This is again a problem that is technically true for all
  Python applications, however the nature of pip is that you're likely to have
  pip installed in every single environment since it is installed by default
  in Python, in pyvenv, and in virtualenv.

* Security. On the surface this is oxymoronic since traditionally vendoring
  tends to make it harder to update a dependent library for security updates
  and that holds true for pip. However given the *other* reasons that exist for
  pip to avoid dependencies the alternative (and what was done historically) is
  for pip to reinvent the wheel itself. This led to pip having implemented
  its own HTTPS verification routines to work around the lack of ssl
  validation in the Python standard library which ended up having similar bugs
  to validation routine in requests/urllib3 but which had to be discovered and
  fixed independently. By reusing the libraries, even though we're vendoring,
  we make it easier to keep pip secure by relying on the great work of our
  dependencies *and* making it easier to actually fix security issues by simply
  pulling in a newer version of the dependencies.

* Bootstrapping. Currently most of the popular methods of installing pip rely
  on the fact that pip is self contained to install pip itself. These tools
  work by bundling a copy of pip, adding it to the sys.path and then executing
  that copy of pip. This is done instead of implementing a "mini" installer to
  again reduce duplication, pip already knows how to install a Python package
  and is going to be vastly more battle tested than any sort of mini installer
  could ever possibly be.

Many downstream redistributors have policies against this kind of bundling and
instead opt to patch the software they distribute to debundle it and make it
rely on the global versions of the software that they already have packaged
(which may have its own patches applied to it). We (the pip team) would prefer
it if pip was *not* debundled in this manner due to the above reasons and
instead we would prefer it if pip would be left intact as it is now. The one
exception to this, is it is acceptable to remove the
``pip/_vendor/requests/cacert.pem`` file provided you ensure that the
``ssl.get_default_verify_paths().cafile`` API returns the correct CA bundle for
your system. This will ensure that pip will use your system provided CA bundle
instead of the copy bundled with pip.

In the longer term, if someone has a *portable* solution to the above problems,
other than the bundling method we currently use, that doesn't add additional
problems that are unreasonable then we would be happy to consider, and possibly
switch to said method. This solution must function correctly across all of the
situation that we expect pip to be used and not mandate some external mechanism
such as OS packages.


pkg_resources
-------------

pkg_resources has been pulled in from setuptools 28.8.0


Modifications
-------------

* html5lib has been modified to import six from pip._vendor
* pkg_resources has been modified to import its externs from pip._vendor
* CacheControl has been modified to import its dependencies from pip._vendor
* packaging has been modified to import its dependencies from pip._vendor
* requests has been modified *not* to optionally load any C dependencies.
* Modified distro to delay importing argparse to avoid errors on 2.6


Debundling
----------

As mentioned in the rationale we, the pip team, would prefer it if pip was not
debundled (other than optionally ``pip/_vendor/requests/cacert.pem``) and that
pip was left intact. However, if you insist on doing so we have a
semi-supported method that we do test in our CI but which requires a bit of
extra work on your end to make it still solve the problems from above.

1. Delete everything in ``pip/_vendor/`` **except** for
   ``pip/_vendor/__init__.py``.

2. Generate wheels for each of pip's dependencies (and any of their
   dependencies) using your patched copies of these libraries. These must be
   placed somewhere on the filesystem that pip can access, by default we will
   assume you've placed them in ``pip/_vendor``.

3. Modify ``pip/_vendor/__init__.py`` so that the ``DEBUNDLED`` variable is
   ``True``.

4. *(Optional)* If you've placed the wheels in a location other than
   ``pip/_vendor/`` then modify ``pip/_vendor/__init__.py`` so that the
   ``WHEEL_DIR`` variable points to the location you've placed them.
