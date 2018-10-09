# -*- coding=utf-8 -*-

from __future__ import absolute_import, print_function, unicode_literals

import io
import os
from pip_shims import Command as PipCommand, cmdoptions
import plette
import six
import vistir


class PipCmd(PipCommand):
    name = "PipCmd"


def get_sources(urls, trusted_hosts):
    trusted_hosts = [six.moves.urllib.parse.urlparse(url).netloc for url in trusted_hosts]
    sources = []
    for url in urls:
        parsed_url = six.moves.urllib.parse.urlparse(url)
        netloc = parsed_url.netloc
        if '@' in netloc:
            _, _, netloc = netloc.rpartition('@')
        name, _, _ = netloc.partition('.')  # Just use the domain name as the source name
        verify_ssl = True
        if netloc in trusted_hosts:
            verify_ssl = False
        sources.append({"url": url, "name": name, "verify_ssl": verify_ssl})
    return sources


def init_project(root=None, python_version=None):
    pipfile_path = os.path.join(root, "Pipfile")
    if os.path.isfile(pipfile_path):
        raise RuntimeError("{0!r} is already a Pipfile project".format(root))
    if not os.path.exists(root):
        vistir.path.mkdir_p(root, mode=0o755)
    pip_command = PipCmd()
    cmdoptions.make_option_group(cmdoptions.index_group, pip_command.parser)
    parsed, _ = pip_command.parser.parse_args([])
    index_urls = [parsed.index_url] + parsed.extra_index_urls
    sources = get_sources(index_urls, parsed.trusted_hosts)
    data = {
        "sources": sources,
        "packages": {},
        "dev-packages": {},
    }
    if python_version:
        data["requires"] = {"python_version": python_version}
    return create_project(pipfile_path=pipfile_path, data=data)


def create_project(pipfile_path, data={}):
    pipfile = plette.pipfiles.Pipfile(data=data)
    with io.open(pipfile_path, "w") as fh:
        pipfile.dump(fh)
    print("Successfully created new pipfile at {0!r}".format(pipfile_path))
    return 0
