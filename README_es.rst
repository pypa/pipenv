Pipenv: Python Development Workflow for Humans
==============================================

.. image:: https://img.shields.io/pypi/v/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/pypi/l/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://badge.buildkite.com/79c7eccf056b17c3151f3c4d0e4c4b8b724539d84f1e037b9b.svg?branch=master
    :target: https://code.kennethreitz.org/source/pipenv/

.. image:: https://img.shields.io/pypi/pyversions/pipenv.svg
    :target: https://pypi.python.org/pypi/pipenv

.. image:: https://img.shields.io/badge/Say%20Thanks-!-1EAEDB.svg
    :target: https://saythanks.io/to/kennethreitz

---------------

**Pipenv** es una herramienta que apunta a traer todo lo mejor del mundo de empaquetado (bundler, composer, npm, cargo, yarn, etc.) al mundo de Python. *Windows es nuestro ciudadano primera-clase, en nuestro mundo*

Automaticamente crea y maneja un entorno virtual para tus proyectos, tan bien como agregar/remover paquetes desde tu ``Pipfile`` como instalar/desisntalar paquetes. También genera el más importante ``Pipfile.lock``, que es usado para producir determinado build

.. image:: http://media.kennethreitz.com.s3.amazonaws.com/pipenv.gif

Los problemas que Pipenv busca resolver son multifaceticos
.. The problems that Pipenv seeks to solve are multi-faceted:

- No necesitas usar más ``pip`` y ``virtualenv`` separados. Trabajan juntos.
- Manejar un archivo ``requirements.txt`` `puede ser problematico <https://www.kennethreitz.org/essays/a-better-pip-workflow>`_, por eso Pipenv usa en su lugar el venidero ``Pipfile`` y ``Pipfile.lock``, el cual es superior para usos básicos
- Los Hashes se usan en todas partes, siempre. Seguridad. Automaticamente expone vulnerabilidades de seguridad.
- Te da insight de tu arbol de dependecias (e.g.``$ pipenv graph``).
- Streamline flujo de desarrollo cargando archivos ``.env``.
.. - Streamline development workflow by loading ``.env`` files.

Instalación
------------

Si estas en MacOS, puedes instalar Pipenv facilmente con Homebrew::

    $ brew install pipenv

O, si estás usando Ubuntu 17.10::

    $ sudo apt install software-properties-common python-software-properties
    $ sudo add-apt-repository ppa:pypa/ppa
    $ sudo apt update
    $ sudo apt install pipenv

De otra manera, solo usa pip::

    $ pip install pipenv

✨🍰✨


☤ User Testimonials
-------------------

**Jannis Leidel**, former pip maintainer—
    *Pipenv is the porcelain I always wanted to build for pip. It fits my brain and mostly replaces virtualenvwrapper and manual pip calls for me. Use it.*

**David Gang**—
    *This package manager is really awesome. For the first time I know exactly what my dependencies are which I installed and what the transitive dependencies are. Combined with the fact that installs are deterministic, makes this package manager first class, like cargo*.

**Justin Myles Holmes**—
    *Pipenv is finally an abstraction meant to engage the mind instead of merely the filesystem.*


☤ Features
----------

- Habilita verdaderos *builds determinantes* mientras facilmente especificas *solo lo que quieres*.
- Genera y verifica hashes en los archivos para bloquear dependecias.
- Automaticamente instala la versión de Python, si ``pyenv`` esta disponible
- Automaticamente busca tu proyecto home, recursivamente, buscando por un ``Pipfile``
- Automaticamente genera un ``Pipfile``, si no existe
- Automaticamente crea un entorno virtual en una locación estandar
- Automaticamente agrega/remueve paquetes a un ``Pipfile`` cuando se instalan/desisntalan
- Automaticamente carga archivos ``.env``, si estos existen.

Los comandos principales son ``install``, ``uninstall`` and ``lock``, el cual genera un ``Pipfile.lock``. Estos tienen la intención de reemplazar el uso de ``$ pip install``, así como manejar manualmente un entorno virtual (para activar uno, corre ``$ pipenv shell``).

Conceptos Básicos
//////////////

- Un entorno virtual se creará automaticamente, cuando no exista.
_ Cuando no se pasen parametros a ``install``, todos los paquetes ``[packages]`` especificados se instalarán.
- Para iniciar un entorno virutal con Python 3, corre ``$ pipenv --three``. 
- Para iniciar un entorno virutal con Python 2, corre ``$ pipenv --two``. 
- De otra manera, cualquier entorno virtual será por defecto.
.. - Otherwise, whatever virtualenv defaults to will be the default.

Otros Comandos
//////////////

- ``shell`` will spawn a shell with the virtualenv activated.
- ``run`` va a correr el comando dado desde el entorno virtual, con algún argumento adelante (e.g. ``$ pipenv run python``)
- ``check`` asegura que los requerimientos en PEP 508 estan being met en el entorno actual.
- ``graph`` va a imprimir un bonito arbol de todas tus dependencias instaladas.

Shell Completion
////////////////

Por ejemplo, con fish, coloca esto en tu ``~/.config/fish/completions/pipenv.fish``::

    eval (pipenv --completion)

Alternativamente, con bash, coloca esto en tu ``.bashrc`` o ``.bash_profile``::

    eval "$(pipenv --completion)"

Magic shell completions are now enabled! There is also a `fish plugin <https://github.com/fisherman/pipenv>`_, which will automatically activate your subshells for you!

Fish is the best shell. You should use it.

☤ Uso
-------

::

    $ pipenv
    Usage: pipenv [OPTIONS] COMMAND [ARGS]...

    Options:
      --where          Output project home information.
      --venv           Output virtualenv information.
      --py             Output Python interpreter information.
      --envs           Output Environment Variable options.
      --rm             Remove the virtualenv.
      --bare           Minimal output.
      --completion     Output completion (to be eval'd).
      --man            Display manpage.
      --three / --two  Use Python 3/2 when creating virtualenv.
      --python TEXT    Specify which version of Python virtualenv should use.
      --site-packages  Enable site-packages for the virtualenv.
      --version        Show the version and exit.
      -h, --help       Show this message and exit.


    Usage Examples:
       Create a new project using Python 3.6, specifically:
       $ pipenv --python 3.6

       Install all dependencies for a project (including dev):
       $ pipenv install --dev

       Create a lockfile containing pre-releases:
       $ pipenv lock --pre

       Show a graph of your installed dependencies:
       $ pipenv graph

       Check your installed dependencies for security vulnerabilities:
       $ pipenv check

       Install a local setup.py into your virtual environment/Pipfile:
       $ pipenv install -e .

       Use a lower-level pip command:
       $ pipenv run pip freeze

    Commands:
      check      Checks for security vulnerabilities and against PEP 508 markers
                 provided in Pipfile.
      clean      Uninstalls all packages not specified in Pipfile.lock.
      graph      Displays currently–installed dependency graph information.
      install    Installs provided packages and adds them to Pipfile, or (if none
                 is given), installs all packages.
      lock       Generates Pipfile.lock.
      open       View a given module in your editor.
      run        Spawns a command installed into the virtualenv.
      shell      Spawns a shell within the virtualenv.
      sync       Installs all packages specified in Pipfile.lock.
      uninstall  Un-installs a provided package and removes it from Pipfile.




Localiza tu proyecto::

    $ pipenv --where
    /Users/kennethreitz/Library/Mobile Documents/com~apple~CloudDocs/repos/kr/pipenv/test

Localiza tu entorno virtual::

   $ pipenv --venv
   /Users/kennethreitz/.local/share/virtualenvs/test-Skyy4vre

Localiza tu interprete de Python::

    $ pipenv --py
    /Users/kennethreitz/.local/share/virtualenvs/test-Skyy4vre/bin/python

Instala paquetes::

    $ pipenv install
    Creating a virtualenv for this project...
    ...
    No package provided, installing all dependencies.
    Virtualenv location: /Users/kennethreitz/.local/share/virtualenvs/test-EJkjoYts
    Installing dependencies from Pipfile.lock...
    ...

    To activate this project's virtualenv, run the following:
    $ pipenv shell

Instala un paquete de desarrollo::

    $ pipenv install pytest --dev
    Installing pytest...
    ...
    Adding pytest to Pipfile's [dev-packages]...

Muestra el arbol de dependecias::

    $ pipenv graph
    requests==2.18.4
      - certifi [required: >=2017.4.17, installed: 2017.7.27.1]
      - chardet [required: >=3.0.2,<3.1.0, installed: 3.0.4]
      - idna [required: >=2.5,<2.7, installed: 2.6]
      - urllib3 [required: <1.23,>=1.21.1, installed: 1.22]

Genera un lockfile::

    $ pipenv lock
    Assuring all dependencies from Pipfile are installed...
    Locking [dev-packages] dependencies...
    Locking [packages] dependencies...
    Note: your project now has only default [packages] installed.
    To install [dev-packages], run: $ pipenv install --dev

Instala todas las dependencias de desarrollo::

    $ pipenv install --dev
    Pipfile found at /Users/kennethreitz/repos/kr/pip2/test/Pipfile. Considering this to be the project home.
    Pipfile.lock out of date, updating...
    Assuring all dependencies from Pipfile are installed...
    Locking [dev-packages] dependencies...
    Locking [packages] dependencies...

Desinstala todo::

    $ pipenv uninstall --all
    No package provided, un-installing all dependencies.
    Found 25 installed package(s), purging...
    ...
    Environment now purged and fresh!

Usa el shell::

    $ pipenv shell
    Loading .env environment variables…
    Launching subshell in virtual environment. Type 'exit' or 'Ctrl+D' to return.
    $ ▯

☤ Documentación
---------------

Documentación esta alojada en `pipenv.org <http://pipenv.org/>`_.
