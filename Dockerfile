FROM python:3.6.2

# System upgrades
apk add --update build-base openssl-dev python-dev

# -- Pyenv Support:
RUN curl -L https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer | bash
ENV PATH "/root/.pyenv/bin:$PATH"
ENV PATH "/root/.pyenv/shims:$PATH"
ENV PYENV_SHELL "bash"
ENV PYENV_ROOT "/root/.pyenv"

# -- Pyenv Version support:
RUN pyenv install 2.6.9
RUN pyenv install 2.7.14
RUN pyenv install 3.3.6
RUN pyenv install 3.4.5
RUN pyenv install 3.5.4
RUN pyenv install 3.6.2

# -- Install Pipenv:
RUN pip install pipenv --upgrade

# -- Install Application into container:
RUN mkdir /app
WORKDIR /app

# --------------------
# - Using This File: -
# --------------------

# FROM kennethreitz/pipenv

# COPY Pipfile Pipfile
# COPY Pipfile.lock Pipfile.lock
# COPY . /app

# -- Install dependencies:
# RUN pipenv install --deploy

ENTRYPOINT []
CMD [ "/bin/bash" ]