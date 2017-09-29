FROM python:3.6.2

# -- Optional Pyenv Support:
# RUN curl -L https://raw.githubusercontent.com/pyenv/pyenv-installer/master/bin/pyenv-installer | bash
# ENV PATH "/root/.pyenv/bin:$PATH"
# RUN eval "$(pyenv init -)"

# -- Optional Pyenv Version support:
# RUN pyenv install 2.6.9
# RUN pyenv install 2.7.14
# RUN pyenv install 3.3.6
# RUN pyenv install 3.4.5
# RUN pyenv install 3.5.4
# RUN pyenv install 3.6.2

# -- Install Pipenv:
RUN pip install pipenv --upgrade

# -- Install Application into container:
RUN mkdir /app
WORKDIR /app
COPY Pipfile Pipfile
COPY Pipfile.lock Pipfile.lock
COPY . /app

# -- Install dependencies:
RUN pipenv install --system --deploy

ENTRYPOINT []
CMD [ "/bin/bash" ]