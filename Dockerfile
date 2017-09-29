FROM python:3.6.2
FROM python:3.4.5
FROM python:3.5.4
FROM python:2.7.14
FROM python:3.3.6

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