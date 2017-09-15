import delegator

from pipenv.utils import python_version


FULL_PYTHON_PATH = 'C:\\Python36-x64\\python.exe'


class TestUtilsWindows():

    def test_python_version_from_full_path(self):
        print(delegator.run('{0} --version'.format(FULL_PYTHON_PATH)).out)

        assert python_version(FULL_PYTHON_PATH) == "3.6.1"
