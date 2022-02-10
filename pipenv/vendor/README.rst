|Logo|

=====================================================================
``yaspin``: **Y**\ et **A**\ nother Terminal **Spin**\ ner for Python
=====================================================================

|Build Status| |Coverage| |Codacy| |pyup| |black-fmt|

|pypi| |Versions| |Wheel| |Examples|

|DownloadsTot| |DownloadsW|


``Yaspin`` provides a full-featured terminal spinner to show the progress during long-hanging operations.

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/demo.gif

It is easy to integrate into existing codebase by using it as a `context manager`_
or as a function `decorator`_:

.. code:: python

    import time
    from yaspin import yaspin

    # Context manager:
    with yaspin():
        time.sleep(3)  # time consuming code

    # Function decorator:
    @yaspin(text="Loading...")
    def some_operations():
        time.sleep(3)  # time consuming code

    some_operations()


**Yaspin** also provides an intuitive and powerful API. For example, you can easily summon a shark:

.. code:: python

    import time
    from yaspin import yaspin

    with yaspin().white.bold.shark.on_blue as sp:
        sp.text = "White bold shark in a blue sea"
        time.sleep(5)

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/shark.gif


Features
--------

- Runs at all major **CPython** versions (*3.6*, *3.7*, *3.8*, *3.9*), **PyPy**
- Supports all (70+) spinners from `cli-spinners`_
- Supports all *colors*, *highlights*, *attributes* and their mixes from `termcolor`_ library
- Easy to combine with other command-line libraries, e.g. `prompt-toolkit`_
- Flexible API, easy to integrate with existing code
- User-friendly API for handling POSIX `signals`_
- Safe **pipes** and **redirects**:

.. code-block:: bash

    $ python script_that_uses_yaspin.py > script.log
    $ python script_that_uses_yaspin.py | grep ERROR


Installation
------------

From `PyPI`_ using ``pip`` package manager:

.. code-block:: bash

    pip install --upgrade yaspin


Or install the latest sources from GitHub:

.. code-block:: bash

    pip install https://github.com/pavdmyt/yaspin/archive/master.zip


Usage
-----

Basic Example
/////////////

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/basic_example.gif

.. code:: python

    import time
    from random import randint
    from yaspin import yaspin

    with yaspin(text="Loading", color="yellow") as spinner:
        time.sleep(2)  # time consuming code

        success = randint(0, 1)
        if success:
            spinner.ok("✅ ")
        else:
            spinner.fail("💥 ")


It is also possible to control spinner manually:

.. code:: python

    import time
    from yaspin import yaspin

    spinner = yaspin()
    spinner.start()

    time.sleep(3)  # time consuming tasks

    spinner.stop()


Run any spinner from `cli-spinners`_
////////////////////////////////////

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/cli_spinners.gif

.. code:: python

    import time
    from yaspin import yaspin
    from yaspin.spinners import Spinners

    with yaspin(Spinners.earth, text="Earth") as sp:
        time.sleep(2)                # time consuming code

        # change spinner
        sp.spinner = Spinners.moon
        sp.text = "Moon"

        time.sleep(2)                # time consuming code


Any Colour You Like `🌈`_
/////////////////////////

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/basic_colors.gif

.. code:: python

    import time
    from yaspin import yaspin

    with yaspin(text="Colors!") as sp:
        # Support all basic termcolor text colors
        colors = ("red", "green", "yellow", "blue", "magenta", "cyan", "white")

        for color in colors:
            sp.color, sp.text = color, color
            time.sleep(1)


Advanced colors usage
/////////////////////

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/advanced_colors.gif

.. code:: python

    import time
    from yaspin import yaspin
    from yaspin.spinners import Spinners

    text = "Bold blink magenta spinner on cyan color"
    with yaspin().bold.blink.magenta.bouncingBall.on_cyan as sp:
        sp.text = text
        time.sleep(3)

    # The same result can be achieved by passing arguments directly
    with yaspin(
        Spinners.bouncingBall,
        color="magenta",
        on_color="on_cyan",
        attrs=["bold", "blink"],
    ) as sp:
        sp.text = text
        time.sleep(3)


Run any spinner you want
////////////////////////

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/custom_spinners.gif

.. code:: python

    import time
    from yaspin import yaspin, Spinner

    # Compose new spinners with custom frame sequence and interval value
    sp = Spinner(["😸", "😹", "😺", "😻", "😼", "😽", "😾", "😿", "🙀"], 200)

    with yaspin(sp, text="Cat!"):
        time.sleep(3)  # cat consuming code :)


Change spinner properties on the fly
////////////////////////////////////

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/sp_properties.gif

.. code:: python

    import time
    from yaspin import yaspin
    from yaspin.spinners import Spinners

    with yaspin(Spinners.noise, text="Noise spinner") as sp:
        time.sleep(2)

        sp.spinner = Spinners.arc  # spinner type
        sp.text = "Arc spinner"    # text along with spinner
        sp.color = "green"         # spinner color
        sp.side = "right"          # put spinner to the right
        sp.reversal = True         # reverse spin direction

        time.sleep(2)


Spinner with timer
//////////////////

.. code:: python

    import time
    from yaspin import yaspin

    with yaspin(text="elapsed time", timer=True) as sp:
        time.sleep(3.1415)
        sp.ok()


Writing messages
////////////////

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/write_text.gif

You should not write any message in the terminal using ``print`` while spinner is open.
To write messages in the terminal without any collision with ``yaspin`` spinner, a ``.write()`` method is provided:

.. code:: python

    import time
    from yaspin import yaspin

    with yaspin(text="Downloading images", color="cyan") as sp:
        # task 1
        time.sleep(1)
        sp.write("> image 1 download complete")

        # task 2
        time.sleep(2)
        sp.write("> image 2 download complete")

        # finalize
        sp.ok("✔")


Integration with other libraries
////////////////////////////////

.. image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/gifs/hide_show.gif

Utilizing ``hidden`` context manager it is possible to toggle the display of
the spinner in order to call custom methods that write to the terminal. This is
helpful for allowing easy usage in other frameworks like `prompt-toolkit`_.
Using the powerful ``print_formatted_text`` function allows you even to apply
HTML formats and CSS styles to the output:

.. code:: python

    import sys
    import time

    from yaspin import yaspin
    from prompt_toolkit import HTML, print_formatted_text
    from prompt_toolkit.styles import Style

    # override print with feature-rich ``print_formatted_text`` from prompt_toolkit
    print = print_formatted_text

    # build a basic prompt_toolkit style for styling the HTML wrapped text
    style = Style.from_dict({
        'msg': '#4caf50 bold',
        'sub-msg': '#616161 italic'
    })


    with yaspin(text='Downloading images') as sp:
        # task 1
        time.sleep(1)
        with sp.hidden():
            print(HTML(
                u'<b>></b> <msg>image 1</msg> <sub-msg>download complete</sub-msg>'
            ), style=style)

        # task 2
        time.sleep(2)
        with sp.hidden():
            print(HTML(
                u'<b>></b> <msg>image 2</msg> <sub-msg>download complete</sub-msg>'
            ), style=style)

        # finalize
        sp.ok()


Handling POSIX `signals`_
/////////////////////////

Handling keyboard interrupts (pressing Control-C):

.. code:: python

    import time

    from yaspin import kbi_safe_yaspin


    with kbi_safe_yaspin(text="Press Control+C to send SIGINT (Keyboard Interrupt) signal"):
        time.sleep(5)  # time consuming code


Handling other types of signals:

.. code:: python

    import os
    import time
    from signal import SIGTERM, SIGUSR1

    from yaspin import yaspin
    from yaspin.signal_handlers import default_handler, fancy_handler


    sigmap = {SIGUSR1: default_handler, SIGTERM: fancy_handler}
    with yaspin(sigmap=sigmap, text="Handling SIGUSR1 and SIGTERM signals") as sp:
        sp.write("Send signals using `kill` command")
        sp.write("E.g. $ kill -USR1 {0}".format(os.getpid()))
        time.sleep(20)  # time consuming code


More `examples`_.


Development
-----------

Clone the repository:

.. code-block:: bash

    git clone https://github.com/pavdmyt/yaspin.git


Install dev dependencies:

.. code-block:: bash

    poetry install

    # if you don't have poetry installed:
    pip install -r requirements.txt


Lint code:

.. code-block:: bash

    make lint


Format code:

.. code-block:: bash

    make black-fmt


Run tests:

.. code-block:: bash

    make test


Contributing
------------

1. Fork it!
2. Create your feature branch: ``git checkout -b my-new-feature``
3. Commit your changes: ``git commit -m 'Add some feature'``
4. Push to the branch: ``git push origin my-new-feature``
5. Submit a pull request
6. Make sure tests are passing


License
-------

* MIT - Pavlo Dmytrenko; https://twitter.com/pavdmyt
* Contains data from `cli-spinners`_: MIT License, Copyright (c) Sindre Sorhus sindresorhus@gmail.com (sindresorhus.com)


.. |Logo| image:: https://raw.githubusercontent.com/pavdmyt/yaspin/master/static/logo_80.png
   :alt: yaspin Logo
.. |Build Status| image:: https://travis-ci.org/pavdmyt/yaspin.svg?branch=master
   :target: https://travis-ci.org/pavdmyt/yaspin
.. |Coverage| image:: https://codecov.io/gh/pavdmyt/yaspin/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/pavdmyt/yaspin
.. |Codacy| image:: https://api.codacy.com/project/badge/Grade/797c7772d0d3467c88a5e2e9dc79ec98
   :target: https://www.codacy.com/app/pavdmyt/yaspin?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=pavdmyt/yaspin&amp;utm_campaign=Badge_Grade
.. |pypi| image:: https://img.shields.io/pypi/v/yaspin.svg
   :target: https://pypi.org/project/yaspin/
.. |Versions| image:: https://img.shields.io/pypi/pyversions/yaspin.svg
   :target: https://pypi.org/project/yaspin/
.. |Wheel| image:: https://img.shields.io/pypi/wheel/yaspin.svg
   :target: https://pypi.org/project/yaspin/
.. |Examples| image:: https://img.shields.io/badge/learn%20by-examples-0077b3.svg
   :target: https://github.com/pavdmyt/yaspin/tree/master/examples
.. |pyup| image:: https://pyup.io/repos/github/pavdmyt/yaspin/shield.svg
   :target: https://pyup.io/repos/github/pavdmyt/yaspin/
.. |black-fmt| image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/ambv/black
.. |DownloadsTot| image:: https://pepy.tech/badge/yaspin
   :target: https://pepy.tech/project/yaspin
.. |DownloadsW| image:: https://pepy.tech/badge/yaspin/week
   :target: https://pepy.tech/project/yaspin


.. _context manager: https://docs.python.org/3/reference/datamodel.html#context-managers
.. _decorator: https://www.thecodeship.com/patterns/guide-to-python-function-decorators/
.. _cli-spinners: https://github.com/sindresorhus/cli-spinners
.. _termcolor: https://pypi.org/project/termcolor/
.. _PyPI: https://pypi.org/
.. _🌈: https://en.wikipedia.org/wiki/Any_Colour_You_Like
.. _examples: https://github.com/pavdmyt/yaspin/tree/master/examples
.. _prompt-toolkit: https://github.com/jonathanslenders/python-prompt-toolkit/
.. _signals: https://www.computerhope.com/unix/signals.htm
