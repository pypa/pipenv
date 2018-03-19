# -*- coding=utf-8 -*-
import os
import pytest
from first import first
from pipenv import requirements
from pipenv.utils import get_requirement, convert_deps_from_pip, convert_deps_to_pip


class TestRequirements:

    @pytest.mark.requirement
    @pytest.mark.parametrize(
        'line, pipfile',
        [
            ['requests', {'requests': '*'}],
            ['requests[socks]', {'requests': {'extras': ['socks'], 'version': '*'}}],
            ['django>1.10', {'django': '>1.10'}],
            ['requests[socks]>1.10', {'requests': {'extras': ['socks'], 'version': '>1.10'}}],
            ['-e git+git://github.com/pinax/pinax.git@1.4#egg=pinax', {'pinax': {'git': 'git://github.com/pinax/pinax.git', 'ref': '1.4', 'editable': True}}],
            ['git+git://github.com/pinax/pinax.git@1.4#egg=pinax', {'pinax': {'git': 'git://github.com/pinax/pinax.git', 'ref': '1.4'}}],
            ['FooProject==1.2 --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824', {'FooProject': {'version': '==1.2', 'hash': 'sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'}}],
            ['FooProject[stuff]==1.2 --hash=sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824', {'FooProject': {'version': '==1.2', 'extras': ['stuff'], 'hash': 'sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'}}],
            ['git+https://github.com/requests/requests.git@master#egg=requests[security]', {'requests': {'git': 'https://github.com/requests/requests.git', 'ref': 'master', 'extras': ['security']}}],
            ['-e svn+svn://svn.myproject.org/svn/MyProject#egg=MyProject', {u'MyProject': {u'svn': u'svn://svn.myproject.org/svn/MyProject', 'editable': True}}],
            ['hg+http://hg.myproject.org/MyProject@da39a3ee5e6b#egg=MyProject', {'MyProject': {'hg': 'http://hg.myproject.org/MyProject', 'ref': 'da39a3ee5e6b'}}]
        ]
    )
    def test_pip_requirements(self, line, pipfile):
        from_line = requirements.PipenvRequirement.from_line(line)
        pipfile_pkgname = first([k for k in pipfile.keys()])
        pipfile_entry = pipfile[pipfile_pkgname]
        from_pipfile = requirements.PipenvRequirement.from_pipfile(pipfile_pkgname, [], pipfile_entry)
        assert from_line.as_pipfile() == pipfile
        assert from_pipfile.as_requirement() == line
