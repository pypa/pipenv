Removed ``pipenv.utils.fileutils.is_valid_url``. Import
``is_valid_url`` from ``pipenv.utils.internet`` instead. pipenv's
stable API is the CLI; internal-only Python imports do not get
a deprecation window. Also removed the
``pipenv.project.SourceNotFound`` re-export for the same reason —
import it from ``pipenv.utils.sources``.
