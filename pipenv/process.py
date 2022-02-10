import os
import subprocess
import threading
from time import monotonic as _time

from pipenv._compat import DEFAULT_ENCODING
from pipenv.cmdparse import Script


class PopenProcess:
    """A wrapper of subprocess.Popen that
    doesn't need to worry about the Pipe buffer exceeding the limit.
    """
    def __init__(
        self, args, *, block=True, encoding=DEFAULT_ENCODING, env=None, timeout=None, **other_kwargs
    ):
        self.blocking = block
        self.env = env
        self.script = Script.parse(args)
        if env is not None:
            env = dict(os.environ, **env)
            other_kwargs['env'] = env
        other_kwargs['stdout'] = subprocess.PIPE
        other_kwargs['stderr'] = subprocess.PIPE
        self._process = subprocess.Popen(args, universal_newlines=True, encoding=encoding, **other_kwargs)
        self._endtime = None
        if timeout is not None:
            self._endtime = _time() + timeout
        self.out_buffer = []
        self.err_buffer = []
        self._start_polling()

    def wait(self):
        try:
            self._process.wait(self._remaining_time())
        except subprocess.TimeoutExpired:
            self._process.kill()
            raise
        finally:
            self.out_reader.join()
            self.err_reader.join()

    @property
    def return_code(self):
        return self._process.returncode

    @property
    def out(self):
        return "".join(self.out_buffer)

    @property
    def err(self):
        return "".join(self.err_buffer)

    def _remaining_time(self):
        if self._endtime is None:
            return None
        return self._endtime - _time()

    def _pipe_output(self):
        for line in iter(self._process.stdout.readline, ""):
            self.out_buffer.append(line)

    def _pipe_err(self):
        for line in iter(self._process.stderr.readline, ""):
            self.err_buffer.append(line)

    def _start_polling(self):
        self.out_reader = threading.Thread(target=self._pipe_output)
        self.err_reader = threading.Thread(target=self._pipe_err)
        self.out_reader.start()
        self.err_reader.start()
