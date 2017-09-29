FROM python:3.6.2

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
# RUN pipenv install --deploy --system

ENTRYPOINT []
CMD [ "/bin/bash" ]