Contributing to pipenv
======================

To work on pipenv itself, fork the repository and clone your fork to your local
system.

Now, install the development requirements::

    cd pipenv
    virtualenv ~/pipenv-venv  # You can use a different path if you like.
    source ~/pipenv-venv/bin/activate
    python setup.py develop
    pipenv install --dev


To run the test suite locally::

    pipenv run pytest tests
