Fix the direct ``pip install safety`` retry in ``pipenv check`` and ``pipenv scan``, which raised a swallowed ``TypeError`` and never ran.
