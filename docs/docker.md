# Docker Containers

In general, you should not have Pipenv inside a linux container image, since
it is a build tool. If you want to use it to build, and install the run time
dependencies for your application, you can use a multistage build for creating
a virtual environment with your dependencies.

In this approach, Pipenv in installed in the base layer, and it is used to create the virtual
environment. In a later stage, in a `runtime` layer the virtual environment
is copied from the base layer, the layer containing pipenv and other build
dependencies is discarded.

This results in a smaller image, which can still run your application.
Here is an example `Dockerfile`, which you can use as a starting point for
doing a multistage build for your application:

    FROM docker.io/oz123/pipenv:3.11-v2023-6-26 AS builder


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

    FROM docker.io/python:3.11 AS runtime

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

```{note}
Pipenv is not meant to run as root. However, in the multistage build above
it is done nevertheless. A calculated risk, since the intermediate image
is discarded.
The runtime image later shows that you should create a user and user it to
run your application.
**Once again, you should not run pipenv as root (or Admin on Windows) normally.
This could lead to breakage of your Python installation, or even your complete
OS.**
```

When you build an image with this example (assuming requests is found in Pipfile), you
will see that `requests` is installed in the `runtime` image:

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
