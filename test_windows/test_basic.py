import delegator


class TestPipenv():

    def test_existience(self):
        assert True

    def test_install(self):
        c = delegator.run('pipenv install')
        assert c.return_code == 0

    def test_lock(self):
        c = delegator.run('pipenv lock')
        assert c.return_code == 0
