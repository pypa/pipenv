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

# -- Install dependencies:
# RUN pipenv install --deploy --system

# -- After installing requirements copy the rest of the code
# COPY . /app

ENTRYPOINT []
CMD [ "/bin/bash" ]
