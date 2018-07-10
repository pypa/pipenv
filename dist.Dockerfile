FROM python:3.6.6-slim-stretch

SHELL ["/usr/bin/env", "bash", "-euxvc"]

RUN apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends binutils wget; \
    wget https://github.com/tianon/gosu/releases/download/1.10/gosu-amd64 -O /usr/local/bin/gosu; \
    chmod 755 /usr/local/bin/gosu; \
    DEBIAN_FRONTEND=noninteractive apt-get purge --auto-remove -y wget; \
    rm -rf /var/lib/apt/lists/*

RUN pip install pyinstaller six


RUN chmod 755 /usr/local/bin/gosu; \
    echo "from pipenv import cli; cli()" > /usr/local/bin/pipenv

CMD groupadd -g ${GROUPID-1000} user; \
    useradd -u ${USERID-1000} -g user user; \
    cd /pipenv; \
    gosu user pyinstaller -p ./pipenv/patched/ \
                -p ./pipenv/vendor/ \
                --onefile \
                /usr/local/bin/pipenv
