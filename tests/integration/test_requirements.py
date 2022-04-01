import pytest


@pytest.mark.requirements
def test_requirements_generates_requirements_from_lockfile(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        packages = ('requests', '2.14.0')
        dev_packages = ('flask', '0.12.2')
        with open(p.pipfile_path, 'w') as f:
            contents = f"""
            [packages]
            {packages[0]}= "=={packages[1]}"
            [dev-packages]
            {dev_packages[0]}= "=={dev_packages[1]}"
            """.strip()
            f.write(contents)
        p.pipenv('lock')
        c = p.pipenv('requirements')
        assert c.returncode == 0
        assert f'{packages[0]}=={packages[1]}' in c.stdout
        assert f'{dev_packages[0]}=={dev_packages[1]}' not in c.stdout

        d = p.pipenv('requirements --dev')
        assert d.returncode == 0
        assert f'{packages[0]}=={packages[1]}' in d.stdout
        assert f'{dev_packages[0]}=={dev_packages[1]}' in d.stdout

        e = p.pipenv('requirements --dev-only')
        assert e.returncode == 0
        assert f'{packages[0]}=={packages[1]}' not in e.stdout
        assert f'{dev_packages[0]}=={dev_packages[1]}' in e.stdout

        e = p.pipenv('requirements --hash')
        assert e.returncode == 0
        assert f'{packages[0]}=={packages[1]}' in e.stdout
        for value in p.lockfile['default'].values():
            for hash in value['hashes']:
                assert f' --hash={hash}' in e.stdout


@pytest.mark.requirements
def test_requirements_generates_requirements_from_lockfile_multiple_sources(PipenvInstance):
    with PipenvInstance(chdir=True) as p:
        packages = ('requests', '2.14.0')
        dev_packages = ('flask', '0.12.2')
        with open(p.pipfile_path, 'w') as f:
            contents = f"""
            [[source]]
            name = "pypi"
            url = "https://pypi.org/simple"
            verify_ssl = true
            [[source]]
            name = "other_source"
            url = "https://$USERNAME:${{PASSWORD}}@some_other_source.org"
            verify_ssl = true
            [packages]
            {packages[0]}= "=={packages[1]}"
            [dev-packages]
            {dev_packages[0]}= "=={dev_packages[1]}"
            """.strip()
            f.write(contents)
        l = p.pipenv('lock')
        assert l.returncode == 0
        c = p.pipenv('requirements')
        assert c.returncode == 0

        assert '-i https://pypi.org/simple' in c.stdout
        assert '--extra-index-url https://$USERNAME:${PASSWORD}@some_other_source.org' in c.stdout
