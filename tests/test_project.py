import pipenv.project

class TestProject():

    def test_project(self):
       proj = pipenv.project.Project()
       assert proj.name == 'pipenv'
       assert proj.pipfile_exists
       assert proj.virtualenv_exists

    def test_pew_by_default(self):
       proj = pipenv.project.Project()
       assert proj.virtualenv_location.endswith('.local/share/virtualenvs/pipenv')
