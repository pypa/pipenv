FROM ubuntu:trusty

# -- Bootstrap the system.
RUN apt-get update -y
RUN apt-get install -y software-properties-common
RUN apt-get install -y python-software-properties
RUN apt-add-repository ppa:deadsnakes/ppa
RUN apt-get update -y

# -- Install all the Pythons.
RUN apt-get install -y python2.6
RUN apt-get install -y python2.7
RUN apt-get install -y python3.1
RUN apt-get install -y python3.2
RUN apt-get install -y python3.3
RUN apt-get install -y python3.4
RUN apt-get install -y python3.5
RUN apt-get install -y python3.6
RUN apt-get install -y python-pip

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