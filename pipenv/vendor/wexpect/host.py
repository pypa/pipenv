"""Host module contains calsses and functions for the host application. These will spawn the child
application. These host classes (and some util classes) are the interface for the user. Handle other
modules as protected.
"""

import time
import sys
import os
import shutil
import re
import traceback
import types
import psutil
import signal
import socket
import logging

import pywintypes
import win32process
import win32con
import win32file
import winerror
import win32pipe

from .wexpect_util import ExceptionPexpect
from .wexpect_util import EOF
from .wexpect_util import TIMEOUT
from .wexpect_util import split_command_line
from .wexpect_util import join_args
from .wexpect_util import init_logger
from .wexpect_util import EOF_CHAR
from .wexpect_util import SIGNAL_CHARS

logger = logging.getLogger('wexpect')


def run(command, timeout=-1, withexitstatus=False, events=None, extra_args=None, logfile=None,
        cwd=None, env=None, **kwargs):
    """
    This function runs the given command; waits for it to finish; then
    returns all output as a string. STDERR is included in output. If the full
    path to the command is not given then the path is searched.

    Note that lines are terminated by CR/LF (\\r\\n) combination even on
    UNIX-like systems because this is the standard for pseudo ttys. If you set
    'withexitstatus' to true, then run will return a tuple of (command_output,
    exitstatus). If 'withexitstatus' is false then this returns just
    command_output.

    The run() function can often be used instead of creating a spawn instance.
    For example, the following code uses spawn::

        child = spawn('scp foo myname@host.example.com:.')
        child.expect ('(?i)password')
        child.sendline (mypassword)

    The previous code can be replace with the following::

        run('scp foo user@example.com:.', events={'(?i)password': mypassword})

    **Examples**

    Start the apache daemon on the local machine::

        run ("/usr/local/apache/bin/apachectl start")

    Check in a file using SVN::

        run ("svn ci -m 'automatic commit' my_file.py")

    Run a command and capture exit status::

        (command_output, exitstatus) = run ('ls -l /bin', withexitstatus=1)

    The following will run SSH and execute 'ls -l' on the remote machine. The
    password 'secret' will be sent if the '(?i)password' pattern is ever seen::

        run ("ssh username@machine.example.com 'ls -l'", events={'(?i)password':'secret\\n'})

    This will start mencoder to rip a video from DVD. This will also display
    progress ticks every 5 seconds as it runs. For example::

        from pipenv.vendor.wexpect import *
        def print_ticks(d):
            print d['event_count'],
        run("mencoder dvd://1 -o video.avi -oac copy -ovc copy",
            events={TIMEOUT:print_ticks}, timeout=5)

    The 'events' argument should be a dictionary of patterns and responses.
    Whenever one of the patterns is seen in the command out run() will send the
    associated response string. Note that you should put newlines in your
    string if Enter is necessary. The responses may also contain callback
    functions. Any callback is function that takes a dictionary as an argument.
    The dictionary contains all the locals from the run() function, so you can
    access the child spawn object or any other variable defined in run()
    (event_count, child, and extra_args are the most useful). A callback may
    return True to stop the current run process otherwise run() continues until
    the next event. A callback may also return a string which will be sent to
    the child. 'extra_args' is not used by directly run(). It provides a way to
    pass data to a callback function through run() through the locals
    dictionary passed to a callback. """

    from .__init__ import spawn
    if timeout == -1:
        child = spawn(command, maxread=2000, logfile=logfile, cwd=cwd, env=env, **kwargs)
    else:
        child = spawn(
            command, timeout=timeout, maxread=2000, logfile=logfile, cwd=cwd, env=env, **kwargs)
    if events is not None:
        patterns = list(events.keys())
        responses = list(events.values())
    else:
        patterns = None   # We assume that EOF or TIMEOUT will save us.
        responses = None
    child_result_list = []
    event_count = 0
    while 1:
        try:
            index = child.expect(patterns)
            if type(child.after) in (str,):
                child_result_list.append(child.before + child.after)
            else:   # child.after may have been a TIMEOUT or EOF, so don't cat those.
                child_result_list.append(child.before)
            if type(responses[index]) in (str,):
                child.send(responses[index])
            elif isinstance(responses[index], types.FunctionType):
                callback_result = responses[index](locals())
                sys.stdout.flush()
                if type(callback_result) in (str,):
                    child.send(callback_result)
                elif callback_result:
                    break
            else:
                logger.warning("TypeError ('The callback must be a string or function type.')")
                raise TypeError('The callback must be a string or function type.')
            event_count = event_count + 1
        except TIMEOUT:
            child_result_list.append(child.before)
            break
        except EOF:
            child_result_list.append(child.before)
            break
    child_result = ''.join(child_result_list)
    if withexitstatus:
        child.wait()
        return (child_result, child.exitstatus)
    else:
        return child_result


class SpawnBase:
    def __init__(self, command, args=[], timeout=30, maxread=60000, searchwindowsize=None,
                 logfile=None, cwd=None, env=None, codepage=None, echo=True, safe_exit=True,
                 interact=False, coverage_console_reader=False, **kwargs):
        """This starts the given command in a child process. This does all the
        fork/exec type of stuff for a pty. This is called by __init__. If args
        is empty then command will be parsed (split on spaces) and args will be
        set to parsed arguments.

        The pid and child_fd of this object get set by this method.
        Note that it is difficult for this method to fail.
        You cannot detect if the child process cannot start.
        So the only way you can tell if the child process started
        or not is to try to read from the file descriptor. If you get
        EOF immediately then it means that the child is already dead.
        That may not necessarily be bad because you may haved spawned a child
        that performs some task; creates no stdout output; and then dies.
        """
        self.host_pid = os.getpid()     # That's me
        self.console_process = None
        self.console_pid = None
        self.child_process = None
        self.child_pid = None

        self.safe_exit = safe_exit
        self.searcher = None
        self.ignorecase = False
        self.before = None
        self.after = None
        self.match = None
        self.match_index = None
        self.terminated = True
        self.exitstatus = None
        self.status = None  # status returned by os.waitpid
        self.flag_eof = False
        self.flag_child_finished = False
        self.child_fd = -1  # initially closed
        self.timeout = timeout
        self.delimiter = EOF
        self.codepage = codepage
        self.cwd = cwd
        self.env = env
        self.echo = echo
        self.coverage_console_reader = coverage_console_reader
        self.maxread = maxread      # max bytes to read at one time into buffer
        # delaybeforesend: Sets sleep time used just before sending data to child. Time in seconds.
        self.delaybeforesend = 0.1
        # delayafterterminate: Sets delay in terminate() method to allow kernel time to update
        # process status. Time in seconds.
        self.delayafterterminate = 0.1
        self.buffer = ''    # This is the read buffer. See maxread.
        # searchwindowsize: Anything before searchwindowsize point is preserved, but not searched.
        self.searchwindowsize = searchwindowsize
        self.interact_state = interact

        logger.info(f'Spawn started. location {os.path.abspath(__file__)}')

        # If command is an int type then it may represent a file descriptor.
        if isinstance(command, int):
            logger.warning(
                "ExceptionPexpect :'Command is an int type. If this is a file descriptor then maybe"
                " you want to use fdpexpect.fdspawn which takes an existing file descriptor instead"
                " of a command string.')")
            raise ExceptionPexpect(
                'Command is an int type. If this is a file descriptor then maybe you want to use'
                ' fdpexpect.fdspawn which takes an existing file descriptor instead of a command '
                'string.')

        if not isinstance(args, list):
            logger.warning("TypeError ('The argument, args, must be a list.')")
            raise TypeError('The argument, args, must be a list.')

        if args == []:
            self.args = split_command_line(command)
            self.command = self.args[0]
        else:
            self.args = args[:]     # work with a copy
            self.args.insert(0, command)
            self.command = command

        command_with_path = shutil.which(self.command)
        if command_with_path is None:
            logger.warning('The command was not found or was not executable: %s.' % self.command)
            raise ExceptionPexpect(
                'The command was not found or was not executable: %s.' % self.command)
        self.command = command_with_path
        self.args[0] = self.command

        self.name = '<' + ' '.join(self.args) + '>'

        self.terminated = False
        self.closed = False

        self.child_fd = self.startChild(self.args, self.env)
        self.get_child_process()
        logger.info(f'Child pid: {self.child_pid}  Console pid: {self.console_pid}')
        self.connect_to_child()

    def __del__(self):
        """This makes sure that no system resources are left open. Python only
        garbage collects Python objects, not the child console."""

        try:
            logger.info('Deleting...')
            if self.child_process is not None:
                self.terminate()
                self.disconnect_from_child()
                if self.safe_exit:
                    self.wait()
        except Exception: # pragma: no cover
            # I hope this code is unreachable...
            logger.error(traceback.format_exc())
            raise

    def __str__(self):
        """This returns a human-readable string that represents the state of
        the object. """

        s = []
        s.append(repr(self))
        s.append('command: ' + str(self.command))
        s.append('args: ' + str(self.args))
        s.append('searcher: ' + str(self.searcher))
        s.append('buffer (last 100 chars): ' + str(self.buffer)[-100:])
        s.append('before (last 100 chars): ' + str(self.before)[-100:])
        s.append('after: ' + str(self.after))
        s.append('match: ' + str(self.match))
        s.append('match_index: ' + str(self.match_index))
        s.append('exitstatus: ' + str(self.exitstatus))
        s.append('flag_eof: ' + str(self.flag_eof))
        s.append('host_pid: ' + str(self.host_pid))
        s.append('child_fd: ' + str(self.child_fd))
        s.append('closed: ' + str(self.closed))
        s.append('timeout: ' + str(self.timeout))
        s.append('delimiter: ' + str(self.delimiter))
        s.append('maxread: ' + str(self.maxread))
        s.append('ignorecase: ' + str(self.ignorecase))
        s.append('searchwindowsize: ' + str(self.searchwindowsize))
        s.append('delaybeforesend: ' + str(self.delaybeforesend))
        s.append('delayafterterminate: ' + str(self.delayafterterminate))
        return '\n'.join(s)

    def startChild(self, args, env):
        '''Start the console process.

        startChild() starts the console process with arguments to command it to create the read
        child process. startChild() does not connect to console, it just creates it.

        The console creation depends on if the host process is running in a normal python process,
        or in a PyInstaller bundle.
        '''

        # startupinfo for Windows' CreateProcess.
        si = win32process.GetStartupInfo()
        si.dwFlags = win32process.STARTF_USESHOWWINDOW
        if not self.interact_state:
            si.wShowWindow = win32con.SW_HIDE

        # collect arguments for console
        self.console_class_parameters.update(
            {
                'console_reader_class': self.console_class_name,
                'host_pid': self.host_pid,
                'local_echo': self.echo,
                'interact': self.interact_state,
                'codepage': self.codepage
            }
        )
        console_class_parameters_kv_pairs = [
            f'--{k}={v}'for k, v in self.console_class_parameters.items() if v is not None
        ]
        console_class_parameters_str = ' '.join(console_class_parameters_kv_pairs)
        args_str = join_args(args)
        console_args = f" {console_class_parameters_str} -- {args_str}"

        # set environment variables for the console
        # Deep copy needed to prevent cycle-to-cycle growth. See #31 for more details.
        environ = os.environ.copy()

        if getattr(sys, 'frozen', False): # pragma: no cover
            '''Runing in a PyInstaller bundle:
            Pyinstaller has no explicit python interpreter, so console-reader should be bundled
            also, and host should call it as a windows executable.

            This code cannot be covered during tests, because it runs only in bundled way.

            https://pyinstaller.readthedocs.io/en/stable/runtime-information.html#using-sys-executable-and-sys-argv-0
            https://github.com/pyinstaller/pyinstaller/issues/822
            '''

            if not hasattr(sys, '_MEIPASS'):
                raise Exception(
                    '`sys.frozen` found, but `sys._MEIPASS` not. Only pyinstaller is supported.'
                )
            dirname = os.path.dirname(sys.executable)

            console_executable = os.path.join(dirname, '..', 'wexpect', 'wexpect.exe')
            commandLine = f'"{console_executable}" {console_args}'

        else:
            '''Runing in a normal python process
            '''
            dirname = os.path.dirname(os.path.abspath(__file__))
            spath = [os.path.dirname(dirname)]

            pyargs = ['-m']
            python_executable = sys.executable

            if self.coverage_console_reader:
                pyargs = ['-m', 'coverage', 'run', '--parallel-mode', '-m']

            # add current location to PYTHONPATH environment variable to be able to start the child.
            python_path = environ.get('PYTHONPATH', '')
            spath = ';'.join(spath)
            environ['PYTHONPATH'] = f'{spath};{python_path}'

            child_class_initializator = f"wexpect {console_args}"

            pyargs = ' '.join(pyargs)
            commandLine = f'"{python_executable}" {pyargs} {child_class_initializator}'

        logger.info(f'Console starter command:{commandLine}')

        # start the console-reader
        _, _, self.console_pid, __otid = win32process.CreateProcess(
            None, commandLine, None, None, False, win32process.CREATE_NEW_CONSOLE, environ,
            self.cwd, si
        )

    def get_console_process(self, force=False):
        if force or self.console_process is None:
            self.console_process = psutil.Process(self.console_pid)
        return self.console_process

    def get_child_process(self, force=False):
        if force or self.console_process is None:
            self.child_process = self.get_console_process()
            self.child_pid = self.child_process.pid
        return self.child_process

    def close(self):   # File-like object.
        """ Closes the child console."""

        self.closed = self.terminate()

    def terminate(self, force=False):
        """Terminate the child. Force not used. """

        if not self.isalive():
            return True

        self.kill()
        if not self.isalive(timeout = self.delayafterterminate):
            return True

        raise ExceptionPexpect("Child has not been terminated even after it was killed.")

    def isalive(self, trust_console=True, timeout=0):
        """True if the child is still alive, false otherwise"""
        if trust_console:
            if self.flag_eof:
                return False

        if self.child_process is None:
            # Child process has not been started... Not alive
            return False

        if self.exitstatus is not None:
            return False

        try:
            self.exitstatus = self.child_process.wait(timeout=timeout)
            logger.info(f'exitstatus: {self.exitstatus}')
            return False
        except psutil.TimeoutExpired:
            return True

    def kill(self, sig=signal.SIGTERM):
        """Sig == sigint for ctrl-c otherwise the child is terminated."""
        try:
            logger.info(f'Sending kill signal: {sig}')
            self.send(SIGNAL_CHARS[sig])
            self.terminated = True
        except EOF as e:
            logger.info(e)

    def wait(self, child=True, console=False):

        if self.exitstatus is not None:
            return self.exitstatus

        if child:
            self.exitstatus = self.child_process.wait()
            logger.info(f'exitstatus: {self.exitstatus}')
        if console:
            self.exitstatus = self.console_process.wait()
            logger.info(f'exitstatus: {self.exitstatus}')
        return self.exitstatus

    def read(self, size=-1):   # File-like object.
        """This reads at most "size" bytes from the file (less if the read hits
        EOF before obtaining size bytes). If the size argument is negative or
        omitted, read all data until EOF is reached. The bytes are returned as
        a string object. An empty string is returned when EOF is encountered
        immediately. """

        if size == 0:
            return ''
        if size < 0:
            self.expect(self.delimiter)     # delimiter default is EOF
            return self.before

        # I could have done this more directly by not using expect(), but
        # I deliberately decided to couple read() to expect() so that
        # I would catch any bugs early and ensure consistant behavior.
        # It's a little less efficient, but there is less for me to
        # worry about if I have to later modify read() or expect().
        # Note, it's OK if size==-1 in the regex. That just means it
        # will never match anything in which case we stop only on EOF.
        cre = re.compile('.{%d}' % size, re.DOTALL)
        index = self.expect([cre, self.delimiter])      # delimiter default is EOF
        if index == 0:
            return self.after   # self.before should be ''. Should I assert this?
        return self.before

    def readline(self, size=-1):    # File-like object.
        """This reads and returns one entire line. A trailing newline is kept
        in the string, but may be absent when a file ends with an incomplete
        line. Note: This readline() looks for a \\r\\n pair even on UNIX
        because this is what the pseudo tty device returns. So contrary to what
        you may expect you will receive the newline as \\r\\n. An empty string
        is returned when EOF is hit immediately. Currently, the size argument is
        mostly ignored, so this behavior is not standard for a file-like
        object. If size is 0 then an empty string is returned. """

        if size == 0:
            return ''
        index = self.expect(['\r\n', self.delimiter])  # delimiter default is EOF
        if index == 0:
            return self.before + '\r\n'
        else:
            return self.before

    def __iter__(self):     # File-like object.
        """This is to support iterators over a file-like object.
        """

        return self

    def read_nonblocking(self, size=1): # pragma: no cover
        """Virtual definition
        """
        raise NotImplementedError

    def __next__(self):     # File-like object.
        """This is to support iterators over a file-like object.
        """

        result = self.readline()
        if self.after == self.delimiter:
            raise StopIteration
        return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.terminate()

    def readlines(self, sizehint=-1):     # File-like object.
        """This reads until EOF using readline() and returns a list containing
        the lines thus read. The optional "sizehint" argument is ignored. """

        lines = []
        while True:
            line = self.readline()
            if not line:
                break
            lines.append(line)
        return lines

    def isatty(self):   # File-like object.
        """The child is always created with a console."""

        return True

    def write(self, s):   # File-like object.
        """This is similar to send() except that there is no return value.
        """

        self.send(s)

    def writelines(self, sequence):   # File-like object.
        """This calls write() for each element in the sequence. The sequence
        can be any iterable object producing strings, typically a list of
        strings. This does not add line separators There is no return value.
        """

        for s in sequence:
            self.write(s)

    def sendline(self, s=''):
        """This is like send(), but it adds a line feed (os.linesep). This
        returns the number of bytes written. """

        n = self.send(s + '\r\n')
        return n

    def sendeof(self):
        """This sends an EOF to the child. This sends a character which causes
        the pending parent output buffer to be sent to the waiting child
        program without waiting for end-of-line. If it is the first character
        of the line, the read() in the user program returns 0, which signifies
        end-of-file. This means to work as expected a sendeof() has to be
        called at the beginning of a line. This method does not send a newline.
        It is the responsibility of the caller to ensure the eof is sent at the
        beginning of a line. """

        # platform does not define VEOF so assume CTRL-D
        char = chr(4)
        self.send(char)

    def send(self, s, delaybeforesend=None):
        """Virtual definition
        """
        if self.flag_eof:
            logger.info('EOF: End of file has been already detected.')
            raise EOF('End of file has been already detected.')

        if delaybeforesend is None:
            delaybeforesend = self.delaybeforesend

        if delaybeforesend:
            time.sleep(delaybeforesend)

        return self._send_impl(s)

    def _send_impl(self, s): # pragma: no cover
        """Virtual definition
        """
        raise NotImplementedError

    def connect_to_child(self): # pragma: no cover
        """Virtual definition
        """
        raise NotImplementedError

    def disconnect_from_child(self): # pragma: no cover
        """Virtual definition
        """
        raise NotImplementedError

    def compile_pattern_list(self, patterns):
        """This compiles a pattern-string or a list of pattern-strings.
        Patterns must be a StringType, EOF, TIMEOUT, SRE_Pattern, or a list of
        those. Patterns may also be None which results in an empty list (you
        might do this if waiting for an EOF or TIMEOUT condition without
        expecting any pattern).

        This is used by expect() when calling expect_list(). Thus expect() is
        nothing more than::

             cpl = self.compile_pattern_list(pl)
             return self.expect_list(cpl, timeout)

        If you are using expect() within a loop it may be more
        efficient to compile the patterns first and then call expect_list().
        This avoid calls in a loop to compile_pattern_list()::

             cpl = self.compile_pattern_list(my_pattern)
             while some_condition:
                ...
                i = self.expect_list(clp, timeout)
                ...
        """

        if patterns is None:
            return []
        if type(patterns) is not list:
            patterns = [patterns]

        compile_flags = re.DOTALL   # Allow dot to match \n
        if self.ignorecase:
            compile_flags = compile_flags | re.IGNORECASE
        compiled_pattern_list = []
        for p in patterns:
            if type(p) in (str,):
                compiled_pattern_list.append(re.compile(p, compile_flags))
            elif p is EOF:
                compiled_pattern_list.append(EOF)
            elif p is TIMEOUT:
                compiled_pattern_list.append(TIMEOUT)
            elif isinstance(p, type(re.compile(''))):
                compiled_pattern_list.append(p)
            else:
                logger.warning(
                    "TypeError: 'Argument must be one of StringTypes, EOF, TIMEOUT, SRE_Pattern, or"
                    " a list of those type. %s' % str(type(p))")
                raise TypeError(
                    'Argument must be one of StringTypes, EOF, TIMEOUT, SRE_Pattern, or a list of'
                    ' those type. %s' % str(type(p)))

        return compiled_pattern_list

    def expect(self, pattern, timeout=-1, searchwindowsize=None):
        """This seeks through the stream until a pattern is matched. The
        pattern is overloaded and may take several types. The pattern can be a
        StringType, EOF, a compiled re, or a list of any of those types.
        Strings will be compiled to re types. This returns the index into the
        pattern list. If the pattern was not a list this returns index 0 on a
        successful match. This may raise exceptions for EOF or TIMEOUT. To
        avoid the EOF or TIMEOUT exceptions add EOF or TIMEOUT to the pattern
        list. That will cause expect to match an EOF or TIMEOUT condition
        instead of raising an exception.

        If you pass a list of patterns and more than one matches, the first match
        in the stream is chosen. If more than one pattern matches at that point,
        the leftmost in the pattern list is chosen. For example::

            # the input is 'foobar'
            index = p.expect (['bar', 'foo', 'foobar'])
            # returns 1 ('foo') even though 'foobar' is a "better" match

        Please note, however, that buffering can affect this behavior, since
        input arrives in unpredictable chunks. For example::

            # the input is 'foobar'
            index = p.expect (['foobar', 'foo'])
            # returns 0 ('foobar') if all input is available at once,
            # but returs 1 ('foo') if parts of the final 'bar' arrive late

        After a match is found the instance attributes 'before', 'after' and
        'match' will be set. You can see all the data read before the match in
        'before'. You can see the data that was matched in 'after'. The
        re.MatchObject used in the re match will be in 'match'. If an error
        occurred then 'before' will be set to all the data read so far and
        'after' and 'match' will be None.

        If timeout is -1 then timeout will be set to the self.timeout value.

        A list entry may be EOF or TIMEOUT instead of a string. This will
        catch these exceptions and return the index of the list entry instead
        of raising the exception. The attribute 'after' will be set to the
        exception type. The attribute 'match' will be None. This allows you to
        write code like this::

                index = p.expect (['good', 'bad', wexpect.EOF, wexpect.TIMEOUT])
                if index == 0:
                    do_something()
                elif index == 1:
                    do_something_else()
                elif index == 2:
                    do_some_other_thing()
                elif index == 3:
                    do_something_completely_different()

        instead of code like this::

                try:
                    index = p.expect (['good', 'bad'])
                    if index == 0:
                        do_something()
                    elif index == 1:
                        do_something_else()
                except EOF:
                    do_some_other_thing()
                except TIMEOUT:
                    do_something_completely_different()

        These two forms are equivalent. It all depends on what you want. You
        can also just expect the EOF if you are waiting for all output of a
        child to finish. For example::

                p = wexpect.spawn('/bin/ls')
                p.expect (wexpect.EOF)
                print p.before

        If you are trying to optimize for speed then see expect_list().
        """

        compiled_pattern_list = self.compile_pattern_list(pattern)
        return self.expect_list(compiled_pattern_list, timeout, searchwindowsize)

    def expect_list(self, pattern_list, timeout=-1, searchwindowsize=-1):
        """This takes a list of compiled regular expressions and returns the
        index into the pattern_list that matched the child output. The list may
        also contain EOF or TIMEOUT (which are not compiled regular
        expressions). This method is similar to the expect() method except that
        expect_list() does not recompile the pattern list on every call. This
        may help if you are trying to optimize for speed, otherwise just use
        the expect() method.  This is called by expect(). If timeout==-1 then
        the self.timeout value is used. If searchwindowsize==-1 then the
        self.searchwindowsize value is used. """

        return self.expect_loop(searcher_re(pattern_list), timeout, searchwindowsize)

    def expect_exact(self, pattern_list, timeout=-1, searchwindowsize=-1):
        """This is similar to expect(), but uses plain string matching instead
        of compiled regular expressions in 'pattern_list'. The 'pattern_list'
        may be a string; a list or other sequence of strings; or TIMEOUT and
        EOF.

        This call might be faster than expect() for two reasons: string
        searching is faster than RE matching and it is possible to limit the
        search to just the end of the input buffer.

        This method is also useful when you don't want to have to worry about
        escaping regular expression characters that you want to match."""

        if not isinstance(pattern_list, list):
            pattern_list = [pattern_list]

        for p in pattern_list:
            if type(p) not in (str,) and p not in (TIMEOUT, EOF):
                logger.warning(
                    'TypeError: Argument must be one of StringTypes, EOF, TIMEOUT, or a list of'
                    ' those type. %s' % str(type(p)))
                raise TypeError(
                    'Argument must be one of StringTypes, EOF, TIMEOUT, or a list of those type. '
                    '%s' % str(type(p)))

        return self.expect_loop(searcher_string(pattern_list), timeout, searchwindowsize)

    def expect_loop(self, searcher, timeout=-1, searchwindowsize=-1):
        """This is the common loop used inside expect. The 'searcher' should be
        an instance of searcher_re or searcher_string, which describes how and what
        to search for in the input.

        See expect() for other arguments, return value and exceptions. """

        self.searcher = searcher

        if timeout == -1:
            timeout = self.timeout
        if timeout is not None:
            end_time = time.time() + timeout
        if searchwindowsize == -1:
            searchwindowsize = self.searchwindowsize

        logger.debug(f'searcher: {searcher}')

        try:
            incoming = self.buffer
            freshlen = len(incoming)
            while True:     # Keep reading until exception or return.
                index = searcher.search(incoming, freshlen, searchwindowsize)
                if index >= 0:
                    self.buffer = incoming[searcher.end:]
                    self.before = incoming[:searcher.start]
                    self.after = incoming[searcher.start:searcher.end]
                    self.match = searcher.match
                    self.match_index = index
                    return self.match_index
                # No match at this point
                if self.flag_eof:
                    raise EOF('EOF flag has been raised.')
                if timeout is not None and end_time < time.time():
                    logger.info('Timeout exceeded in expect_any().')
                    raise TIMEOUT('Timeout exceeded in expect_any().')
                # Still have time left, so read more data
                self.isalive()
                c = self.read_nonblocking(self.maxread)
                freshlen = len(c)
                time.sleep(0.01)
                incoming += c
        except EOF as e:
            self.buffer = ''
            self.before = incoming
            self.after = EOF
            index = searcher.eof_index
            if index >= 0:
                self.match = EOF
                self.match_index = index
                return self.match_index
            else:
                self.match = None
                self.match_index = None
                logger.info('Raise EOF again')
                raise
        except TIMEOUT as e:
            self.buffer = incoming
            self.before = incoming
            self.after = TIMEOUT
            index = searcher.timeout_index
            if index >= 0:
                self.match = TIMEOUT
                self.match_index = index
                return self.match_index
            else:
                self.match = None
                self.match_index = None
                logger.info(f'TIMEOUT: {e}\n{self}')
                raise TIMEOUT(f'{e}\n{self}')
        except Exception:
            self.before = incoming
            self.after = None
            self.match = None
            self.match_index = None
            raise


class SpawnPipe(SpawnBase):

    def __init__(self, command, args=[], timeout=30, maxread=60000, searchwindowsize=None,
                 logfile=None, cwd=None, env=None, codepage=None, echo=True, interact=False,
                 **kwargs):
        self.pipe = None
        self.console_class_name = 'ConsoleReaderPipe'
        self.console_class_parameters = {}

        super().__init__(
            command=command, args=args, timeout=timeout, maxread=maxread,
            searchwindowsize=searchwindowsize, cwd=cwd, env=env, codepage=codepage, echo=echo,
            interact=interact, **kwargs)

        # Sets delay in terminate() method to allow kernel time to update process status. Time in
        # seconds.
        self.delayafterterminate = 2

    def connect_to_child(self):
        pipe_name = 'wexpect_{}'.format(self.console_pid)
        pipe_full_path = r'\\.\pipe\{}'.format(pipe_name)
        logger.debug(f'Trying to connect to pipe: {pipe_full_path}')
        while True:
            try:
                self.pipe = win32file.CreateFile(
                    pipe_full_path,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None
                )
                logger.debug('Pipe found')
                res = win32pipe.SetNamedPipeHandleState(self.pipe, win32pipe.PIPE_READMODE_MESSAGE,
                                                        None, None)
                if res == 0:
                    logger.debug(f"SetNamedPipeHandleState return code: {res}")
                return
            except pywintypes.error as e:
                if e.args[0] == winerror.ERROR_FILE_NOT_FOUND:      # 2
                    logger.debug("no pipe, trying again in a bit later")
                    time.sleep(0.2)
                else:
                    raise

    def disconnect_from_child(self):
        if self.pipe:
            win32file.CloseHandle(self.pipe)

    def read_nonblocking(self, size=1):
        """This reads at most size characters from the child application. If
        the end of file is read then an EOF exception will be raised.

        This is not effected by the 'size' parameter, so if you call
        read_nonblocking(size=100, timeout=30) and only one character is
        available right away then one character will be returned immediately.
        It will not wait for 30 seconds for another 99 characters to come in.

        This is a wrapper around Wtty.read(). """

        if self.closed:
            logger.warning('I/O operation on closed file in read_nonblocking().')
            raise ValueError('I/O operation on closed file in read_nonblocking().')

        try:
            s = win32file.ReadFile(self.pipe, size)[1]

            if s:
                logger.debug(f'Readed: {s}')
            else:
                logger.spam(f'Readed: {s}')

            if EOF_CHAR in s:
                self.flag_eof = True
                logger.info("EOF: EOF character has been arrived")
                s = s.split(EOF_CHAR)[0]

            return s.decode()
        except pywintypes.error as e:
            if e.args[0] == winerror.ERROR_BROKEN_PIPE:   # 109
                self.flag_eof = True
                logger.info("EOF('broken pipe, bye bye')")
                raise EOF('broken pipe, bye bye')
            elif e.args[0] == winerror.ERROR_NO_DATA:
                '''232 (0xE8): The pipe is being closed.
                '''
                self.flag_eof = True
                logger.info("EOF('The pipe is being closed.')")
                raise EOF('The pipe is being closed.')
            else:
                raise

    def _send_impl(self, s):
        """This sends a string to the child process. This returns the number of
        bytes written. If a log file was set then the data is also written to
        the log. """
        if isinstance(s, str):
            s = str.encode(s)
        try:
            if s:
                logger.debug(f"Writing: {s}")
            win32file.WriteFile(self.pipe, s)
            logger.spam(f"WriteFile finished.")
        except pywintypes.error as e:
            if e.args[0] == winerror.ERROR_BROKEN_PIPE:   # 109
                logger.info("EOF: broken pipe, bye bye")
                self.flag_eof = True
                raise EOF("broken pipe, bye bye")
            elif e.args[0] == winerror.ERROR_NO_DATA:
                '''232 (0xE8)
                The pipe is being closed.
                '''
                logger.info("The pipe is being closed.")
                self.flag_eof = True
                raise EOF("The pipe is being closed.")
            else:
                raise
        return len(s)


class SpawnSocket(SpawnBase):

    def __init__(self, command, args=[], timeout=30, maxread=60000, searchwindowsize=None,
                 logfile=None, cwd=None, env=None, codepage=None, echo=True, port=4321,
                 host='127.0.0.1', interact=False, **kwargs):
        self.port = port
        self.host = host
        self.sock = None
        self.console_class_name = 'ConsoleReaderSocket'
        self.console_class_parameters = {'port': port}

        super().__init__(
            command=command, args=args, timeout=timeout, maxread=maxread,
            searchwindowsize=searchwindowsize, cwd=cwd, env=env, codepage=codepage, echo=echo,
            interact=interact, **kwargs)

        # Sets delay in terminate() method to allow kernel time to update process status. Time in
        # seconds.
        self.delayafterterminate = 2

    def _send_impl(self, s):
        """This sends a string to the child process. This returns the number of
        bytes written. If a log file was set then the data is also written to
        the log. """
        if isinstance(s, str):
            s = str.encode(s)
        try:
            if s:
                logger.debug(f"Writing: {s}")
            self.sock.sendall(s)
            logger.spam(f"WriteFile finished.")
            return len(s)
        except ConnectionResetError as e:
            logger.info("ConnectionResetError")
            self.flag_eof = True
            raise EOF("ConnectionResetError")

    def connect_to_child(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        self.sock.settimeout(.2)

    def disconnect_from_child(self):
        logger.info('disconnect_from_child')
        if self.sock:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            self.sock = None

    def read_nonblocking(self, size=1):
        """This reads at most size characters from the child application. If
        the end of file is read then an EOF exception will be raised.

        This is not effected by the 'size' parameter, so if you call
        read_nonblocking(size=100, timeout=30) and only one character is
        available right away then one character will be returned immediately.
        It will not wait for 30 seconds for another 99 characters to come in.

        This is a wrapper around Wtty.read(). """

        if self.closed:
            logger.info('I/O operation on closed file in read_nonblocking().')
            raise ValueError('I/O operation on closed file in read_nonblocking().')

        try:
            s = self.sock.recv(size)

            if s:
                logger.debug(f'Readed: {s}')
            else:
                logger.spam(f'Readed: {s}')

            if EOF_CHAR in s:
                self.flag_eof = True
                logger.info("EOF: EOF character has been arrived")
                s = s.split(EOF_CHAR)[0]

        except ConnectionResetError:
            self.flag_eof = True
            logger.info("EOF('ConnectionResetError')")
            raise EOF('ConnectionResetError')
        except socket.timeout:
            return ''

        return s.decode()


class searcher_re (object):
    """This is regular expression string search helper for the
    spawn.expect_any() method.

    Attributes:

        eof_index     - index of EOF, or -1
        timeout_index - index of TIMEOUT, or -1

    After a successful match by the search() method the following attributes
    are available:

        start - index into the buffer, first byte of match
        end   - index into the buffer, first byte after match
        match - the re.match object returned by a succesful re.search

    """

    def __init__(self, patterns):
        """This creates an instance that searches for 'patterns' Where
        'patterns' may be a list or other sequence of compiled regular
        expressions, or the EOF or TIMEOUT types."""

        self.eof_index = -1
        self.timeout_index = -1
        self._searches = []
        for n, s in zip(list(range(len(patterns))), patterns):
            if s is EOF:
                self.eof_index = n
                continue
            if s is TIMEOUT:
                self.timeout_index = n
                continue
            self._searches.append((n, s))

    def __str__(self):
        """This returns a human-readable string that represents the state of
        the object."""

        ss = [(n, '    %d: re.compile("%s")' % (n, str(s.pattern))) for n, s in self._searches]
        ss.append((-1, 'searcher_re:'))
        if self.eof_index >= 0:
            ss.append((self.eof_index, '    %d: EOF' % self.eof_index))
        if self.timeout_index >= 0:
            ss.append((self.timeout_index, '    %d: TIMEOUT' % self.timeout_index))
        ss.sort()
        ss = list(zip(*ss))[1]
        return '\n'.join(ss)

    def search(self, buffer, freshlen, searchwindowsize=None):
        """This searches 'buffer' for the first occurence of one of the regular
        expressions. 'freshlen' must indicate the number of bytes at the end of
        'buffer' which have not been searched before.

        See class spawn for the 'searchwindowsize' argument.

        If there is a match this returns the index of that string, and sets
        'start', 'end' and 'match'. Otherwise, returns -1."""

        absurd_match = len(buffer)
        first_match = absurd_match
        # 'freshlen' doesn't help here -- we cannot predict the
        # length of a match, and the re module provides no help.
        if searchwindowsize is None:
            searchstart = 0
        else:
            searchstart = max(0, len(buffer) - searchwindowsize)
        for index, s in self._searches:
            match = s.search(buffer, searchstart)
            if match is None:
                continue
            n = match.start()
            if n < first_match:
                first_match = n
                the_match = match
                best_index = index
        if first_match == absurd_match:
            return -1
        self.start = first_match
        self.match = the_match
        self.end = self.match.end()
        return best_index


class searcher_string (object):
    """This is a plain string search helper for the spawn.expect_any() method.

    Attributes:

        eof_index     - index of EOF, or -1
        timeout_index - index of TIMEOUT, or -1

    After a successful match by the search() method the following attributes
    are available:

        start - index into the buffer, first byte of match
        end   - index into the buffer, first byte after match
        match - the matching string itself
    """

    def __init__(self, strings):
        """This creates an instance of searcher_string. This argument 'strings'
        may be a list; a sequence of strings; or the EOF or TIMEOUT types. """

        self.eof_index = -1
        self.timeout_index = -1
        self._strings = []
        for n, s in zip(list(range(len(strings))), strings):
            if s is EOF:
                self.eof_index = n
                continue
            if s is TIMEOUT:
                self.timeout_index = n
                continue
            self._strings.append((n, s))

    def __str__(self):
        """This returns a human-readable string that represents the state of
        the object."""

        ss = [(ns[0], '    %d: "%s"' % ns) for ns in self._strings]
        ss.append((-1, 'searcher_string:'))
        if self.eof_index >= 0:
            ss.append((self.eof_index, '    %d: EOF' % self.eof_index))
        if self.timeout_index >= 0:
            ss.append((self.timeout_index, '    %d: TIMEOUT' % self.timeout_index))
        ss.sort()
        ss = list(zip(*ss))[1]
        return '\n'.join(ss)

    def search(self, buffer, freshlen, searchwindowsize=None):
        """This searches 'buffer' for the first occurence of one of the search
        strings.  'freshlen' must indicate the number of bytes at the end of
        'buffer' which have not been searched before. It helps to avoid
        searching the same, possibly big, buffer over and over again.

        See class spawn for the 'searchwindowsize' argument.

        If there is a match this returns the index of that string, and sets
        'start', 'end' and 'match'. Otherwise, this returns -1. """

        absurd_match = len(buffer)
        first_match = absurd_match

        # 'freshlen' helps a lot here. Further optimizations could
        # possibly include:
        #
        # using something like the Boyer-Moore Fast String Searching
        # Algorithm; pre-compiling the search through a list of
        # strings into something that can scan the input once to
        # search for all N strings; realize that if we search for
        # ['bar', 'baz'] and the input is '...foo' we need not bother
        # rescanning until we've read three more bytes.
        #
        # Sadly, I don't know enough about this interesting topic. /grahn

        for index, s in self._strings:
            if searchwindowsize is None:
                # the match, if any, can only be in the fresh data,
                # or at the very end of the old data
                offset = -(freshlen + len(s))
            else:
                # better obey searchwindowsize
                offset = -searchwindowsize
            n = buffer.find(s, offset)
            if n >= 0 and n < first_match:
                first_match = n
                best_index, best_match = index, s
        if first_match == absurd_match:
            return -1
        self.match = best_match
        self.start = first_match
        self.end = self.start + len(self.match)
        return best_index
