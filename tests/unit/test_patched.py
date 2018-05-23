from __future__ import absolute_import

import pytest

from notpip._internal.index import PackageFinder


get_extras_links_scenarios = {
    'windows and not windows': (
        [
            'chardet',
            '[:platform_system != "windows"]',
            'twisted',
            '[:platform_system == "windows"]',
            'twisted[windows_platform]',
        ],
        {
            ':platform_system != "windows"': [
                'twisted',
            ],
            ':platform_system == "windows"': [
                'twisted[windows_platform]',
            ],
        },
    ),
    'requests': (
        [
            'chardet<3.1.0,>=3.0.2',
            'idna<2.7,>=2.5',
            'urllib3<1.23,>=1.21.1',
            'certifi>=2017.4.17',
            '[security]',
            'pyOpenSSL>=0.14',
            'cryptography>=1.3.4',
            'idna>=2.0.0',
            '[socks]',
            'PySocks!=1.5.7,>=1.5.6',
            (
                '[socks:sys_platform == "win32"'
                ' and (python_version == "2.7" or python_version == "2.6")]'
            ),
            'win_inet_pton',
        ],
        {
            'security': [
                'pyOpenSSL>=0.14',
                'cryptography>=1.3.4',
                'idna>=2.0.0',
            ],
            'socks': [
                'PySocks!=1.5.7,>=1.5.6',
            ],
            'socks:sys_platform == "win32" '
            'and (python_version == "2.7" or python_version == "2.6")': [
                'win_inet_pton',
            ],
        }
    ),
    'attrs': (
        [
            '[dev]',
            'coverage',
            'hypothesis',
            'pympler',
            'pytest',
            'six',
            'zope.interface',
            'sphinx',
            'zope.interface',
            '[docs]',
            'sphinx',
            'zope.interface',
            '[tests]',
            'coverage',
            'hypothesis',
            'pympler',
            'pytest',
            'six',
            'zope.interface',
        ],
        {
            'dev': [
                'coverage',
                'hypothesis',
                'pympler',
                'pytest',
                'six',
                'zope.interface',
                'sphinx',
                'zope.interface',
            ],
            'docs': [
                'sphinx',
                'zope.interface',
            ],
            'tests': [
                'coverage',
                'hypothesis',
                'pympler',
                'pytest',
                'six',
                'zope.interface',
            ],
        },
    ),
    'misc': (
        [
            'chardet',
            '[:platform_system != "windows"]',
            'attrs',
            '[:platform_system == "windows"]',
            'pytz',
        ],
        {
            ':platform_system != "windows"': [
                'attrs',
            ],
            ':platform_system == "windows"': [
                'pytz',
            ],
        },
    ),
}

@pytest.mark.parametrize(
    'scenarios,expected',
    list(get_extras_links_scenarios.values()),
    ids=list(get_extras_links_scenarios.keys()),
)
def test_get_extras_links(scenarios, expected):
    assert PackageFinder.get_extras_links(scenarios) == expected
