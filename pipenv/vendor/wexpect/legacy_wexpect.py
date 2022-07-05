"""Wexpect is a Windows variant of pexpect https://pexpect.readthedocs.io.

Wexpect is a Python module for spawning child applications and controlling
them automatically. Wexpect can be used for automating interactive applications
such as ssh, ftp, passwd, telnet, etc. It can be used to a automate setup
scripts for duplicating software package installations on different servers. It
can be used for automated software testing. Wexpect is in the spirit of Don
Libes' Expect, but Wexpect is pure Python. Other Expect-like modules for Python
require TCL and Expect or require C extensions to be compiled. Wexpect does not
use C, Expect, or TCL extensions.

There are two main interfaces to Wexpect -- the function, run() and the class,
spawn. You can call the run() function to execute a command and return the
output. This is a handy replacement for os.system().

For example::

    wexpect.run('ls -la')

The more powerful interface is the spawn class. You can use this to spawn an
external child command and then interact with the child by sending lines and
expecting responses.

For example::

    child = wexpect.spawn('scp foo myname@host.example.com:.')
    child.expect('Password:')
    child.sendline(mypassword)

This works even for commands that ask for passwords or other input outside of
the normal stdio streams.

"""

#
# wexpect is windows only. Use pexpect on linux like systems.
#
import sys
if sys.platform != 'win32': # pragma: no cover
    raise ImportError ("""sys.platform != 'win32': Wexpect supports only Windows.
Pexpect is intended for UNIX-like operating systems.""")

#
# Import built in modules
#
import logging
import os
import time
import re
import shutil
import types
import traceback
import signal
import pkg_resources
from io import StringIO

try:
    from ctypes import windll
    import pywintypes
    import win32console
    import win32process
    import win32con
    import win32gui
    import win32api
    import win32file
    import winerror
except ImportError as e: # pragma: no cover
    raise ImportError(str(e) + "\nThis package requires the win32 python packages.\r\nInstall with pip install pywin32")

#
# System-wide constants
#
screenbufferfillchar = '\4'
maxconsoleY = 8000

# The version is handled by the package: pbr, which derives the version from the git tags.
try:
    __version__ = pkg_resources.require("wexpect")[0].version
except: # pragma: no cover
    __version__ = '0.0.1.unkowndev0'

__all__ = ['ExceptionPexpect', 'EOF', 'TIMEOUT', 'spawn', 'run', 'which',
    'split_command_line', '__version__']

#
# Create logger: We write logs only to file. Printing out logs are dangerous, because of the deep
# console manipulation.
#
pid=os.getpid()
logger = logging.getLogger('wexpect')
try:
    logger_level = os.environ['WEXPECT_LOGGER_LEVEL']
    logger.setLevel(logger_level)
    fh = logging.FileHandler(f'wexpect_{pid}.log', 'w', 'utf-8')
    formatter = logging.Formatter('%(asctime)s - %(filename)s::%(funcName)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
except KeyError:
    logger.setLevel(logging.ERROR)

# Test the logger
logger.info('wexpect imported; logger working')

####################################################################################################
#
#        Exceptions
#
####################################################################################################

class ExceptionPexpect(Exception):
    """Base class for all exceptions raised by this module.
    """

    def __init__(self, value):

        self.value = value

    def __str__(self):

        return str(self.value)

    def get_trace(self):
        """This returns an abbreviated stack trace with lines that only concern
        the caller. In other words, the stack trace inside the Wexpect module
        is not included. """

        tblist = traceback.extract_tb(sys.exc_info()[2])
        tblist = [item for item in tblist if self.__filter_not_wexpect(item)]
        tblist = traceback.format_list(tblist)
        return ''.join(tblist)

    def __filter_not_wexpect(self, trace_list_item):
        """This returns True if list item 0 the string 'wexpect.py' in it. """

        if trace_list_item[0].find('wexpect.py') == -1:
            return True
        else:
            return False


class EOF(ExceptionPexpect):
    """Raised when EOF is read from a child. This usually means the child has exited.
    The user can wait to EOF, which means he waits the end of the execution of the child process."""

class TIMEOUT(ExceptionPexpect):
    """Raised when a read time exceeds the timeout. """


def run (command, timeout=-1, withexitstatus=False, events=None, extra_args=None, logfile=None,
    cwd=None, env=None, echo=True):

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

    Examples
    ========

    Start the apache daemon on the local machine::

        run ("/usr/local/apache/bin/apachectl start")

    Check in a file using SVN::

        run ("svn ci -m 'automatic commit' my_file.py")

    Run a command and capture exit status::

        (command_output, exitstatus) = run ('ls -l /bin', withexitstatus=1)

    Tricky Examples
    ===============

    The following will run SSH and execute 'ls -l' on the remote machine. The
    password 'secret' will be sent if the '(?i)password' pattern is ever seen::

        run ("ssh username@machine.example.com 'ls -l'", events={'(?i)password':'secret\\n'})

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

    if timeout == -1:
        child = spawn(command, maxread=2000, logfile=logfile, cwd=cwd, env=env)
    else:
        child = spawn(command, timeout=timeout, maxread=2000, logfile=logfile, cwd=cwd, env=env)
    if events is not None:
        patterns = list(events.keys())
        responses = list(events.values())
    else:
        patterns=None # We assume that EOF or TIMEOUT will save us.
        responses=None
    child_result_list = []
    event_count = 0
    while 1:
        try:
            index = child.expect (patterns)
            if type(child.after) in (str,):
                child_result_list.append(child.before + child.after)
            else: # child.after may have been a TIMEOUT or EOF, so don't cat those.
                child_result_list.append(child.before)
            if type(responses[index]) in (str,):
                child.send(responses[index])
            elif type(responses[index]) is types.FunctionType:
                callback_result = responses[index](locals())
                sys.stdout.flush()
                if type(callback_result) in (str,):
                    child.send(callback_result)
                elif callback_result:
                    break
            else:
                logger.info('TypeError: The callback must be a string or function type.')
                raise TypeError ('The callback must be a string or function type.')
            event_count = event_count + 1
        except TIMEOUT:
            child_result_list.append(child.before)
            break
        except EOF:
            child_result_list.append(child.before)
            break
    child_result = ''.join(child_result_list)
    if withexitstatus:
        child.close()
        return (child_result, child.exitstatus)
    else:
        return child_result

def spawn(command, args=[], timeout=30, maxread=2000, searchwindowsize=None, logfile=None, cwd=None,
    env=None, codepage=None, echo=True, **kwargs):
    """This is the most essential function. The command parameter may be a string that
    includes a command and any arguments to the command. For example::

        child = wexpect.spawn ('/usr/bin/ftp')
        child = wexpect.spawn ('/usr/bin/ssh user@example.com')
        child = wexpect.spawn ('ls -latr /tmp')

    You may also construct it with a list of arguments like so::

        child = wexpect.spawn ('/usr/bin/ftp', [])
        child = wexpect.spawn ('/usr/bin/ssh', ['user@example.com'])
        child = wexpect.spawn ('ls', ['-latr', '/tmp'])

    After this the child application will be created and will be ready to
    talk to. For normal use, see expect() and send() and sendline().

    Remember that Wexpect does NOT interpret shell meta characters such as
    redirect, pipe, or wild cards (>, |, or *). This is a common mistake.
    If you want to run a command and pipe it through another command then
    you must also start a shell. For example::

        child = wexpect.spawn('/bin/bash -c "ls -l | grep LOG > log_list.txt"')
        child.expect(wexpect.EOF)

    The second form of spawn (where you pass a list of arguments) is useful
    in situations where you wish to spawn a command and pass it its own
    argument list. This can make syntax more clear. For example, the
    following is equivalent to the previous example::

        shell_cmd = 'ls -l | grep LOG > log_list.txt'
        child = wexpect.spawn('/bin/bash', ['-c', shell_cmd])
        child.expect(wexpect.EOF)

    The maxread attribute sets the read buffer size. This is maximum number
    of bytes that Wexpect will try to read from a TTY at one time. Setting
    the maxread size to 1 will turn off buffering. Setting the maxread
    value higher may help performance in cases where large amounts of
    output are read back from the child. This feature is useful in
    conjunction with searchwindowsize.

    The searchwindowsize attribute sets the how far back in the incomming
    seach buffer Wexpect will search for pattern matches. Every time
    Wexpect reads some data from the child it will append the data to the
    incomming buffer. The default is to search from the beginning of the
    imcomming buffer each time new data is read from the child. But this is
    very inefficient if you are running a command that generates a large
    amount of data where you want to match The searchwindowsize does not
    effect the size of the incomming data buffer. You will still have
    access to the full buffer after expect() returns.

    The delaybeforesend helps overcome a weird behavior that many users
    were experiencing. The typical problem was that a user would expect() a
    "Password:" prompt and then immediately call sendline() to send the
    password. The user would then see that their password was echoed back
    to them. Passwords don't normally echo. The problem is caused by the
    fact that most applications print out the "Password" prompt and then
    turn off stdin echo, but if you send your password before the
    application turned off echo, then you get your password echoed.
    Normally this wouldn't be a problem when interacting with a human at a
    real keyboard. If you introduce a slight delay just before writing then
    this seems to clear up the problem. This was such a common problem for
    many users that I decided that the default wexpect behavior should be
    to sleep just before writing to the child application. 1/20th of a
    second (50 ms) seems to be enough to clear up the problem. You can set
    delaybeforesend to 0 to return to the old behavior. Most Linux machines
    don't like this to be below 0.03. I don't know why.

    Note that spawn is clever about finding commands on your path.
    It uses the same logic that "which" uses to find executables.

    If you wish to get the exit status of the child you must call the
    close() method. The exit status of the child will be stored in self.exitstatus.
    If the child exited normally then exitstatus will store the exit return code.
    """

    logger.debug('=' * 80)
    logger.debug('Buffer size: %s' % maxread)
    if searchwindowsize:
        logger.debug('Search window size: %s' % searchwindowsize)
    logger.debug('Timeout: %ss' % timeout)
    if env:
        logger.debug('Environment:')
        for name in env:
            logger.debug('\t%s=%s' % (name, env[name]))
    if cwd:
        logger.debug('Working directory: %s' % cwd)

    return spawn_windows(command, args, timeout, maxread, searchwindowsize, logfile, cwd, env,
                             codepage, echo=echo)

class spawn_windows ():
    """This is the main class interface for Wexpect. Use this class to start
    and control child applications. """

    def __init__(self, command, args=[], timeout=30, maxread=60000, searchwindowsize=None,
        logfile=None, cwd=None, env=None, codepage=None, echo=True):
        """ The spawn_windows constructor. Do not call it directly. Use spawn(), or run() instead.
        """
        self.codepage = codepage

        self.stdin = sys.stdin
        self.stdout = sys.stdout
        self.stderr = sys.stderr

        self.searcher = None
        self.ignorecase = False
        self.before = None
        self.after = None
        self.match = None
        self.match_index = None
        self.terminated = True
        self.exitstatus = None
        self.status = None # status returned by os.waitpid
        self.flag_eof = False
        self.flag_child_finished = False
        self.pid = None
        self.child_fd = -1 # initially closed
        self.timeout = timeout
        self.delimiter = EOF
        self.logfile = logfile
        self.logfile_read = None # input from child (read_nonblocking)
        self.logfile_send = None # output to send (send, sendline)
        self.maxread = maxread # max bytes to read at one time into buffer
        self.buffer = '' # This is the read buffer. See maxread.
        self.searchwindowsize = searchwindowsize # Anything before searchwindowsize point is preserved, but not searched.
        self.delaybeforesend = 0.05 # Sets sleep time used just before sending data to child. Time in seconds.
        self.delayafterterminate = 0.1 # Sets delay in terminate() method to allow kernel time to update process status. Time in seconds.
        self.name = '<' + repr(self) + '>' # File-like object.
        self.closed = True # File-like object.
        self.ocwd = os.getcwd()
        self.cwd = cwd
        self.env = env

        # allow dummy instances for subclasses that may not use command or args.
        if command is None:
            self.command = None
            self.args = None
            self.name = '<wexpect factory incomplete>'
        else:
            self._spawn(command, args, echo=echo)

    def __del__(self):
        """This makes sure that no system resources are left open. Python only
        garbage collects Python objects, not the child console."""

        try:
            self.wtty.terminate_child()
        except:
            pass

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
        s.append('pid: ' + str(self.pid))
        s.append('child_fd: ' + str(self.child_fd))
        s.append('closed: ' + str(self.closed))
        s.append('timeout: ' + str(self.timeout))
        s.append('delimiter: ' + str(self.delimiter))
        s.append('logfile: ' + str(self.logfile))
        s.append('logfile_read: ' + str(self.logfile_read))
        s.append('logfile_send: ' + str(self.logfile_send))
        s.append('maxread: ' + str(self.maxread))
        s.append('ignorecase: ' + str(self.ignorecase))
        s.append('searchwindowsize: ' + str(self.searchwindowsize))
        s.append('delaybeforesend: ' + str(self.delaybeforesend))
        s.append('delayafterterminate: ' + str(self.delayafterterminate))
        return '\n'.join(s)

    def _spawn(self,command,args=[], echo=True):
        """This starts the given command in a child process. This does all the
        fork/exec type of stuff for a pty. This is called by __init__. If args
        is empty then command will be parsed (split on spaces) and args will be
        set to parsed arguments. """

        # The pid and child_fd of this object get set by this method.
        # Note that it is difficult for this method to fail.
        # You cannot detect if the child process cannot start.
        # So the only way you can tell if the child process started
        # or not is to try to read from the file descriptor. If you get
        # EOF immediately then it means that the child is already dead.
        # That may not necessarily be bad because you may haved spawned a child
        # that performs some task; creates no stdout output; and then dies.

        # If command is an int type then it may represent a file descriptor.
        if type(command) == type(0):
            logger.info('ExceptionPexpect: Command is an int type. If this is a file descriptor then maybe you want to use fdpexpect.fdspawn which takes an existing file descriptor instead of a command string.')
            raise ExceptionPexpect ('Command is an int type. If this is a file descriptor then maybe you want to use fdpexpect.fdspawn which takes an existing file descriptor instead of a command string.')

        if type (args) != type([]):
            logger.info('TypeError: The argument, args, must be a list.')
            raise TypeError ('The argument, args, must be a list.')

        if args == []:
            self.args = split_command_line(command)
            self.command = self.args[0]
        else:
            self.args = args[:] # work with a copy
            self.args.insert (0, command)
            self.command = command

        command_with_path = shutil.which(self.command)
        if command_with_path is None:
           logger.info('ExceptionPexpect: The command was not found or was not executable: %s.' % self.command)
           raise ExceptionPexpect ('The command was not found or was not executable: %s.' % self.command)
        self.command = command_with_path
        self.args[0] = self.command

        self.name = '<' + ' '.join (self.args) + '>'

        #assert self.pid is None, 'The pid member should be None.'
        #assert self.command is not None, 'The command member should not be None.'

        self.wtty = Wtty(codepage=self.codepage, echo=echo)

        if self.cwd is not None:
            os.chdir(self.cwd)

        self.child_fd = self.wtty.spawn(self.command, self.args, self.env)

        if self.cwd is not None:
            # Restore the original working dir
            os.chdir(self.ocwd)

        self.terminated = False
        self.closed = False
        self.pid = self.wtty.pid


    def fileno (self):   # File-like object.
        """There is no child fd."""

        return 0

    def close(self, force=True):   # File-like object.
        """ Closes the child console."""

        self.closed = self.terminate(force)
        if not self.closed:
            logger.info('ExceptionPexpect: close() could not terminate the child using terminate()')
            raise ExceptionPexpect ('close() could not terminate the child using terminate()')
        self.closed = True

    def isatty(self):   # File-like object.
        """The child is always created with a console."""

        return True

    def waitnoecho (self, timeout=-1):
        """This waits until the terminal ECHO flag is set False. This returns
        True if the echo mode is off. This returns False if the ECHO flag was
        not set False before the timeout. This can be used to detect when the
        child is waiting for a password. Usually a child application will turn
        off echo mode when it is waiting for the user to enter a password. For
        example, instead of expecting the "password:" prompt you can wait for
        the child to set ECHO off::

            p = wexpect.spawn ('ssh user@example.com')
            p.waitnoecho()
            p.sendline(mypassword)

        If timeout is None then this method to block forever until ECHO flag is
        False.

        """

        if timeout == -1:
            timeout = self.timeout
        if timeout is not None:
            end_time = time.time() + timeout
        while True:
            if not self.getecho():
                return True
            if timeout < 0 and timeout is not None:
                return False
            if timeout is not None:
                timeout = end_time - time.time()
            time.sleep(0.1)

    def getecho (self):
        """This returns the terminal echo mode. This returns True if echo is
        on or False if echo is off. Child applications that are expecting you
        to enter a password often set ECHO False. See waitnoecho()."""

        return self.wtty.getecho()

    def setecho (self, state):
        """This sets the terminal echo mode on or off."""

        self.wtty.setecho(state)

    def read (self, size = -1):   # File-like object.

        """This reads at most "size" bytes from the file (less if the read hits
        EOF before obtaining size bytes). If the size argument is negative or
        omitted, read all data until EOF is reached. The bytes are returned as
        a string object. An empty string is returned when EOF is encountered
        immediately. """

        if size == 0:
            return ''
        if size < 0:
            self.expect (self.delimiter) # delimiter default is EOF
            return self.before

        # I could have done this more directly by not using expect(), but
        # I deliberately decided to couple read() to expect() so that
        # I would catch any bugs early and ensure consistant behavior.
        # It's a little less efficient, but there is less for me to
        # worry about if I have to later modify read() or expect().
        # Note, it's OK if size==-1 in the regex. That just means it
        # will never match anything in which case we stop only on EOF.
        cre = re.compile('.{%d}' % size, re.DOTALL)
        index = self.expect ([cre, self.delimiter]) # delimiter default is EOF
        if index == 0:
            return self.after ### self.before should be ''. Should I assert this?
        return self.before

    def readline (self, size = -1):    # File-like object.

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
        index = self.expect (['\r\n', self.delimiter]) # delimiter default is EOF
        if index == 0:
            return self.before + '\r\n'
        else:
            return self.before

    def __iter__ (self):    # File-like object.

        """This is to support iterators over a file-like object.
        """

        return self

    def __next__ (self):    # File-like object.

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

    def readlines (self, sizehint = -1):    # File-like object.

        """This reads until EOF using readline() and returns a list containing
        the lines thus read. The optional "sizehint" argument is ignored. """

        lines = []
        while True:
            line = self.readline()
            if not line:
                break
            lines.append(line)
        return lines

    def read_nonblocking (self, size = 1):
        """This reads at most size characters from the child application. If
        the end of file is read then an EOF exception will be raised.

        This is not effected by the 'size' parameter, so if you call
        read_nonblocking(size=100, timeout=30) and only one character is
        available right away then one character will be returned immediately.
        It will not wait for 30 seconds for another 99 characters to come in.

        This is a wrapper around Wtty.read(). """

        if self.closed:
            logger.info('ValueError: I/O operation on closed file in read_nonblocking().')
            raise ValueError ('I/O operation on closed file in read_nonblocking().')

        try:
            # The real child and it's console are two different process. The console dies 0.1 sec
            # later to be able to read the child's last output (before EOF). So here we check
            # isalive() (which checks the real child.) and try a last read on the console. To catch
            # the last output.
            # The flag_child_finished flag shows that this is the second trial, where we raise the EOF.
            if self.flag_child_finished:
                logger.info('EOF: self.flag_child_finished')
                raise EOF('self.flag_child_finished')
            if not self.isalive():
                self.flag_child_finished = True
            s = self.wtty.read_nonblocking(size)
        except EOF:
            self.flag_eof = True
            raise

        if self.logfile is not None:
            self.logfile.write (s)
            self.logfile.flush()
        if self.logfile_read is not None:
            self.logfile_read.write (s)
            self.logfile_read.flush()

        return s

    def write(self, s):   # File-like object.

        """This is similar to send() except that there is no return value.
        """

        self.send (s)

    def writelines (self, sequence):   # File-like object.

        """This calls write() for each element in the sequence. The sequence
        can be any iterable object producing strings, typically a list of
        strings. This does not add line separators There is no return value.
        """

        for s in sequence:
            self.write (s)

    def sendline(self, s=''):

        """This is like send(), but it adds a line feed (os.linesep). This
        returns the number of bytes written. """

        n = self.send(s)
        n = n + self.send (os.linesep)
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

    def send(self, s):
        """This sends a string to the child process. This returns the number of
        bytes written. If a log file was set then the data is also written to
        the log. """

        (self.delaybeforesend)
        if self.logfile is not None:
            self.logfile.write (s)
            self.logfile.flush()
        if self.logfile_send is not None:
            self.logfile_send.write (s)
            self.logfile_send.flush()
        c = self.wtty.write(s)
        return c

    def sendintr(self):
        """This sends a SIGINT to the child. It does not require
        the SIGINT to be the first character on a line. """

        self.wtty.sendintr()

    def eof (self):

        """This returns True if the EOF exception was ever raised.
        """

        return self.flag_eof

    def terminate(self, force=False):
        """Terminate the child. Force not used. """

        if not self.isalive():
            return True

        self.wtty.terminate_child()
        time.sleep(self.delayafterterminate)
        if not self.isalive():
            return True

        return False

    def kill(self, sig=signal.SIGTERM):
        """Sig == sigint for ctrl-c otherwise the child is terminated."""

        if not self.isalive():
            return

        if sig == signal.SIGINT:
            self.wtty.sendintr()
        else:
            self.wtty.terminate_child()

    def wait(self):
        """This waits until the child exits. This is a blocking call. This will
        not read any data from the child, so this will block forever if the
        child has unread output and has terminated. In other words, the child
        may have printed output then called exit(); but, technically, the child
        is still alive until its output is read."""

        # We can't use os.waitpid under Windows because of 'permission denied'
        # exception? Perhaps if not running as admin (or UAC enabled under
        # Vista/7). Simply loop and wait for child to exit.
        while self.isalive():
            time.sleep(.05)  # Keep CPU utilization down

        return self.exitstatus

    def isalive(self):
        """Determines if the child is still alive."""

        if self.terminated:
            logger.debug('self.terminated is true')
            return False

        if self.wtty.isalive():
            return True
        else:
            logger.debug('self.wtty.isalive() is false')
            self.exitstatus = win32process.GetExitCodeProcess(self.wtty.getchild())
            self.status = (self.pid, self.exitstatus << 8)  # left-shift exit status by 8 bits like os.waitpid
            self.terminated = True
            return False

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

        compile_flags = re.DOTALL # Allow dot to match \n
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
            elif type(p) is type(re.compile('')):
                compiled_pattern_list.append(p)
            else:
                logger.info('TypeError: Argument must be one of StringTypes, EOF, TIMEOUT, SRE_Pattern, or a list of those type. %s' % str(type(p)))
                raise TypeError ('Argument must be one of StringTypes, EOF, TIMEOUT, SRE_Pattern, or a list of those type. %s' % str(type(p)))

        return compiled_pattern_list

    def expect(self, pattern, timeout = -1, searchwindowsize=None):

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

    def expect_list(self, pattern_list, timeout = -1, searchwindowsize = -1):

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

    def expect_exact(self, pattern_list, timeout = -1, searchwindowsize = -1):

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
                logger.info('TypeError: Argument must be one of StringTypes, EOF, TIMEOUT, or a list of those type. %s' % str(type(p)))
                raise TypeError ('Argument must be one of StringTypes, EOF, TIMEOUT, or a list of those type. %s' % str(type(p)))

        return self.expect_loop(searcher_string(pattern_list), timeout, searchwindowsize)

    def expect_loop(self, searcher, timeout = -1, searchwindowsize = -1):

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

        try:
            incoming = self.buffer
            freshlen = len(incoming)
            while True: # Keep reading until exception or return.
                index = searcher.search(incoming, freshlen, searchwindowsize)
                if index >= 0:
                    self.buffer = incoming[searcher.end : ]
                    self.before = incoming[ : searcher.start]
                    self.after = incoming[searcher.start : searcher.end]
                    self.match = searcher.match
                    self.match_index = index
                    return self.match_index
                # No match at this point
                if timeout is not None and end_time < time.time():
                    logger.info('TIMEOUT: Timeout exceeded in expect_any().')
                    raise TIMEOUT ('Timeout exceeded in expect_any().')
                # Still have time left, so read more data
                c = self.read_nonblocking(self.maxread)
                freshlen = len(c)
                time.sleep (0.01)
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
                logger.info(str(e) + '\n' + str(self))
                raise EOF (str(e) + '\n' + str(self))
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
                logger.info(str(e) + '\n' + str(self))
                raise TIMEOUT (str(e) + '\n' + str(self))
        except:
            self.before = incoming
            self.after = None
            self.match = None
            self.match_index = None
            raise

    def getwinsize(self):
        """This returns the terminal window size of the child tty. The return
        value is a tuple of (rows, cols). """

        return self.wtty.getwinsize()

    def setwinsize(self, r, c):
        """Set the size of the child screen buffer. """

        self.wtty.setwinsize(r, c)

    def interact(self):
        """Makes the child console visible for interaction"""

        self.wtty.interact()

    def stop_interact(self):
        """Hides the child console from the user."""

        self.wtty.stop_interact()

##############################################################################
# End of spawn_windows class
##############################################################################

class Wtty:

    def __init__(self, timeout=30, codepage=None, echo=True):
        self.__buffer = StringIO()
        self.__bufferY = 0
        self.__currentReadCo = win32console.PyCOORDType(0, 0)
        self.__consSize = [80, 16000]
        self.__parentPid = 0
        self.__oproc = 0
        self.conpid = 0
        self.__otid = 0
        self.__switch = True
        self.__childProcess = None
        self.__conProcess = None
        self.codepage = codepage
        self.console = False
        self.lastRead = 0
        self.lastReadData = ""
        self.pid = None
        self.processList = []
        self.__consout = None
        # We need a timeout for connecting to the child process
        self.timeout = timeout
        self.totalRead = 0
        self.local_echo = echo

    def spawn(self, command, args=[], env=None):
        """Spawns spawner.py with correct arguments."""

        ts = time.time()
        self.startChild(args, env)

        logger.info(f"Fetch child's process and pid...")

        while True:
            msg = win32gui.GetMessage(0, 0, 0)
            childPid = msg[1][2]
            # Sometimes win32gui.GetMessage returns a bogus PID, so keep calling it
            # until we can successfully connect to the child or timeout is
            # reached
            if childPid:
                try:
                    self.__childProcess = win32api.OpenProcess(
                        win32con.PROCESS_TERMINATE | win32con.PROCESS_QUERY_INFORMATION, False, childPid)
                    self.__conProcess = win32api.OpenProcess(
                        win32con.PROCESS_TERMINATE | win32con.PROCESS_QUERY_INFORMATION, False, self.conpid)
                except pywintypes.error:
                    if time.time() > ts + self.timeout:
                        break
                else:
                    self.pid = childPid
                    break
            time.sleep(.05)

        logger.info(f"Child's pid: {self.pid}")

        if not self.__childProcess:
            logger.info('ExceptionPexpect: The process ' + args[0] + ' could not be started.')
            raise ExceptionPexpect ('The process ' + args[0] + ' could not be started.')



        winHandle = int(win32console.GetConsoleWindow())

        self.__switch = True

        if winHandle != 0:
            self.__parentPid = win32process.GetWindowThreadProcessId(winHandle)[1]
            # Do we have a console attached? Do not rely on winHandle, because
            # it will also be non-zero if we didn't have a console, and then
            # spawned a child process! Using sys.stdout.isatty() seems safe
            self.console = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
            # If the original process had a console, record a list of attached
            # processes so we can check if we need to reattach/reallocate the
            # console later
            self.processList = win32console.GetConsoleProcessList()
        else:
            self.switchTo(False)
            self.__switch = False

    def startChild(self, args, env):
        si = win32process.GetStartupInfo()
        si.dwFlags = win32process.STARTF_USESHOWWINDOW
        si.wShowWindow = win32con.SW_HIDE
        # Determine the directory of wexpect.py or, if we are running 'frozen'
        # (eg. py2exe deployment), of the packed executable

        dirname = os.path.dirname(sys.executable
                                  if getattr(sys, 'frozen', False) else
                                  os.path.abspath(__file__))
        if getattr(sys, 'frozen', False):
            logdir = os.path.splitext(sys.executable)[0]
        else:
            logdir = dirname
        logdir = os.path.basename(logdir)
        spath = [os.path.dirname(dirname)]
        pyargs = ['-c']
        if getattr(sys, 'frozen', False):
            # If we are running 'frozen', add library.zip and lib\library.zip
            # to sys.path
            # py2exe: Needs appropriate 'zipfile' option in setup script and
            # 'bundle_files' 3
            spath.append(os.path.join(dirname, 'library.zip'))
            spath.append(os.path.join(dirname, 'library.zip',
                                      os.path.basename(os.path.splitext(sys.executable)[0])))
            if os.path.isdir(os.path.join(dirname, 'lib')):
                dirname = os.path.join(dirname, 'lib')
                spath.append(os.path.join(dirname, 'library.zip'))
                spath.append(os.path.join(dirname, 'library.zip',
                                          os.path.basename(os.path.splitext(sys.executable)[0])))
            pyargs.insert(0, '-S')  # skip 'import site'
        pid = win32process.GetCurrentProcessId()
        tid = win32api.GetCurrentThreadId()
        cp = self.codepage or windll.kernel32.GetACP()
        # If we are running 'frozen', expect python.exe in the same directory
        # as the packed executable.
        # py2exe: The python executable can be included via setup script by
        # adding it to 'data_files'

        if getattr(sys, 'frozen', False):
            python_executable = os.path.join(dirname, 'python.exe')
        else:
            python_executable = os.path.join(os.path.dirname(sys.executable), 'python.exe')

        commandLine = '"%s" %s "%s"' % (python_executable,
                                        ' '.join(pyargs),
                                        f"import sys; sys.path = {spath} + sys.path;"
                                        f"args = {args}; import wexpect;"
                                        f"wexpect.ConsoleReader(wexpect.join_args(args), {pid}, {tid}, cp={cp}, logdir={logdir})"
                                        )

        logger.info(f'CreateProcess: {commandLine}')

        self.__oproc, x, self.conpid, self.__otid = win32process.CreateProcess(None, commandLine, None, None, False,
                                                                  win32process.CREATE_NEW_CONSOLE, env, None, si)
        logger.info(f'self.__oproc: {self.__oproc}')
        logger.info(f'x: {x}')
        logger.info(f'self.conpid: {self.conpid}')
        logger.info(f'self.__otid: {self.__otid}')

    def switchTo(self, attatched=True):
        """Releases from the current console and attatches
        to the childs."""

        if not self.__switch:
            return

        try:
            # No 'attached' check is needed, FreeConsole() can be called multiple times.
            win32console.FreeConsole()
            # This is the workaround for #14. The #14 will still occure if the child process
            # finishes between this `isalive()` check and `AttachConsole(self.conpid)`. (However the
            # risk is low.)
            if not self.isalive(console=True):
                # When child has finished...
                logger.info('EOF: End Of File (EOF) in switchTo().')
                raise EOF('End Of File (EOF) in switchTo().')

            win32console.AttachConsole(self.conpid)
            self.__consin = win32console.GetStdHandle(win32console.STD_INPUT_HANDLE)
            self.__consout = self.getConsoleOut()

        except pywintypes.error as e:
            # pywintypes.error: (5, 'AttachConsole', 'Access is denied.')
            # When child has finished...
            logging.info(e)
            # In case of any error: We "switch back" (attach) our original console, then raise the
            # error.
            self.switchBack()
            logger.info('EOF: End Of File (EOF) in switchTo().')
            raise EOF('End Of File (EOF) in switchTo().')
        except:
            # In case of any error: We "switch back" (attach) our original console, then raise the
            # error.
            self.switchBack()
            logger.info(traceback.format_exc())
            raise


    def switchBack(self):
        """Releases from the current console and attaches
        to the parents."""

        if not self.__switch:
            return

        if self.console:
            # If we originally had a console, re-attach it (or allocate a new one)
            # If we didn't have a console to begin with, there's no need to
            # re-attach/allocate
            win32console.FreeConsole()
            if len(self.processList) > 1:
                # Our original console is still present, re-attach
                win32console.AttachConsole(self.__parentPid)
            else:
                # Our original console has been free'd, allocate a new one
                win32console.AllocConsole()

        self.__consin = None
        self.__consout = None

    def getConsoleOut(self):
        consout = win32file.CreateFile('CONOUT$',
                                       win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                       win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                       None,
                                       win32con.OPEN_EXISTING,
                                       0,
                                       0)

        return win32console.PyConsoleScreenBufferType(consout)

    def getchild(self):
        """Returns a handle to the child process."""

        return self.__childProcess

    def terminate_child(self):
        """Terminate the child process."""
        win32api.TerminateProcess(self.__childProcess, 1)
        # win32api.win32process.TerminateProcess(self.__childProcess, 1)

    def createKeyEvent(self, char):
        """Creates a single key record corrosponding to
            the ascii character char."""

        evt = win32console.PyINPUT_RECORDType(win32console.KEY_EVENT)
        evt.KeyDown = True
        evt.Char = char
        evt.RepeatCount = 1
        return evt

    def write(self, s):
        """Writes input into the child consoles input buffer."""

        if len(s) == 0:
            return 0
        self.switchTo()
        try:
            if s[-1] == '\n':
                s = s[:-1]
            records = [self.createKeyEvent(c) for c in str(s)]
            if not self.__consout:
                return ""

            # Store the current cursor position to hide characters in local echo disabled mode (workaround).
            consinfo = self.__consout.GetConsoleScreenBufferInfo()
            startCo = consinfo['CursorPosition']

            # Send the string to console input
            wrote = self.__consin.WriteConsoleInput(records)

            # Wait until all input has been recorded by the console.
            ts = time.time()
            while self.__consin.PeekConsoleInput(8) != ():
                if time.time() > ts + len(s) * .1 + .5:
                    break
                time.sleep(.05)

            # Hide characters in local echo disabled mode (workaround).
            if not self.local_echo:
                self.__consout.FillConsoleOutputCharacter(screenbufferfillchar, len(s), startCo)

            return wrote
        finally:
            self.switchBack()

    def getCoord(self, offset):
        """Converts an offset to a point represented as a tuple."""

        x = offset % self.__consSize[0]
        y = offset // self.__consSize[0]
        return win32console.PyCOORDType(x, y)

    def getOffset(self, coord):
        """Converts a tuple-point to an offset."""

        return coord.X + coord.Y * self.__consSize[0]

    def readConsole(self, startCo, endCo):
        """Reads the console area from startCo to endCo and returns it
        as a string."""

        buff = []
        self.lastRead = 0

        while True:
            startOff = self.getOffset(startCo)
            endOff = self.getOffset(endCo)
            readlen = endOff - startOff

            if readlen <= 0:
                break

            if readlen > 4000:
                readlen = 4000
            endPoint = self.getCoord(startOff + readlen)

            s = self.__consout.ReadConsoleOutputCharacter(readlen, startCo)
            self.lastRead += len(s)
            self.totalRead += len(s)
            buff.append(s)

            startCo = endPoint

        return ''.join(buff)

    def parseData(self, s):
        """Ensures that special characters are interpretted as
        newlines or blanks, depending on if there written over
        characters or screen-buffer-fill characters."""

        strlist = []
        for i, c in enumerate(s):
            if c == screenbufferfillchar:
                if (self.totalRead - self.lastRead + i + 1) % self.__consSize[0] == 0:
                    strlist.append('\r\n')
            else:
                strlist.append(c)

        s = ''.join(strlist)
        return s


    def readConsoleToCursor(self):
        """Reads from the current read position to the current cursor
        position and inserts the string into self.__buffer."""

        if not self.__consout:
            return ""

        consinfo = self.__consout.GetConsoleScreenBufferInfo()
        cursorPos = consinfo['CursorPosition']

        logger.debug('cursor: %r, current: %r' % (cursorPos, self.__currentReadCo))

        isSameX = cursorPos.X == self.__currentReadCo.X
        isSameY = cursorPos.Y == self.__currentReadCo.Y
        isSamePos = isSameX and isSameY

        logger.debug('isSameY: %r' % isSameY)
        logger.debug('isSamePos: %r' % isSamePos)

        if isSameY or not self.lastReadData.endswith('\r\n'):
            # Read the current slice again
            self.totalRead -= self.lastRead
            self.__currentReadCo.X = 0
            self.__currentReadCo.Y = self.__bufferY

        logger.debug('cursor: %r, current: %r' % (cursorPos, self.__currentReadCo))

        raw = self.readConsole(self.__currentReadCo, cursorPos)
        rawlist = []
        while raw:
            rawlist.append(raw[:self.__consSize[0]])
            raw = raw[self.__consSize[0]:]
        raw = ''.join(rawlist)
        s = self.parseData(raw)
        logger.debug(s)
        for i, line in enumerate(reversed(rawlist)):
            if line.endswith(screenbufferfillchar):
                # Record the Y offset where the most recent line break was detected
                self.__bufferY += len(rawlist) - i
                break

        logger.debug('lastReadData: %r' % self.lastReadData)
        logger.debug('s: %r' % s)

        if isSamePos and self.lastReadData == s:
            logger.debug('isSamePos and self.lastReadData == s')
            s = ''

        logger.debug('s: %r' % s)

        if s:
            lastReadData = self.lastReadData
            pos = self.getOffset(self.__currentReadCo)
            self.lastReadData = s
            if isSameY or not lastReadData.endswith('\r\n'):
                # Detect changed lines
                self.__buffer.seek(pos)
                buf = self.__buffer.read()
                logger.debug('buf: %r' % buf)
                logger.debug('raw: %r' % raw)
                if raw.startswith(buf):
                    # Line has grown
                    rawslice = raw[len(buf):]
                    # Update last read bytes so line breaks can be detected in parseData
                    lastRead = self.lastRead
                    self.lastRead = len(rawslice)
                    s = self.parseData(rawslice)
                    self.lastRead = lastRead
                else:
                    # Cursor has been repositioned
                    s = '\r' + s
                logger.debug('s:   %r' % s)
            self.__buffer.seek(pos)
            self.__buffer.truncate()
            self.__buffer.write(raw)

        self.__currentReadCo.X = cursorPos.X
        self.__currentReadCo.Y = cursorPos.Y

        return s


    def read_nonblocking(self, size):
        """Reads data from the console if available, otherwise
           returns empty string"""

        try:
            self.switchTo()
            time.sleep(.01)

            if self.__currentReadCo.Y > maxconsoleY:
                time.sleep(.2)

            s = self.readConsoleToCursor()

            if self.__currentReadCo.Y > maxconsoleY:
                self.refreshConsole()

            return s

        finally:
            self.switchBack()

        raise Exception('Unreachable code...') # pragma: no cover


    def refreshConsole(self):
        """Clears the console after pausing the child and
        reading all the data currently on the console."""

        orig = win32console.PyCOORDType(0, 0)
        self.__consout.SetConsoleCursorPosition(orig)
        self.__currentReadCo.X = 0
        self.__currentReadCo.Y = 0
        writelen = self.__consSize[0] * self.__consSize[1]
        # Use NUL as fill char because it displays as whitespace
        # (if we interact() with the child)
        self.__consout.FillConsoleOutputCharacter(screenbufferfillchar, writelen, orig)

        self.__bufferY = 0
        self.__buffer.truncate(0)

        consinfo = self.__consout.GetConsoleScreenBufferInfo()
        cursorPos = consinfo['CursorPosition']
        logger.debug('refreshConsole: cursorPos %s' % cursorPos)


    def setecho(self, state):
        """Sets the echo mode of the child console.
        This is a workaround of the setecho. The original GetConsoleMode() / SetConsoleMode()
        methods didn't work. See git history for the concrete implementation.
        2020.01.09 raczben
        """

        self.local_echo = state

    def getecho(self):
        """Returns the echo mode of the child console.
        This is a workaround of the getecho. The original GetConsoleMode() / SetConsoleMode()
        methods didn't work. See git history for the concrete implementation.
        2020.01.09 raczben
        """

        return self.local_echo

    def getwinsize(self):
        """Returns the size of the child console as a tuple of
        (rows, columns)."""

        self.switchTo()
        try:
            size = self.__consout.GetConsoleScreenBufferInfo()['Size']
        finally:
            self.switchBack()
        return (size.Y, size.X)

    def setwinsize(self, r, c):
        """Sets the child console screen buffer size to (r, c)."""

        self.switchTo()
        try:
            self.__consout.SetConsoleScreenBufferSize(win32console.PyCOORDType(c, r))
        finally:
            self.switchBack()

    def interact(self):
        """Displays the child console for interaction."""

        self.switchTo()
        try:
            win32gui.ShowWindow(win32console.GetConsoleWindow(), win32con.SW_SHOW)
        finally:
            self.switchBack()

    def stop_interact(self):
        """Hides the child console."""

        self.switchTo()
        try:
            win32gui.ShowWindow(win32console.GetConsoleWindow(), win32con.SW_HIDE)
        finally:
            self.switchBack()

    def isalive(self, console=False):
        """True if the child is still alive, false otherwise"""

        if console:
            return win32process.GetExitCodeProcess(self.__conProcess) == win32con.STILL_ACTIVE
        else:
            return win32process.GetExitCodeProcess(self.__childProcess) == win32con.STILL_ACTIVE

class ConsoleReader: # pragma: no cover

    def __init__(self, path, pid, tid, env = None, cp=None, logdir=None):
        self.logdir = logdir
        logger.info('consolepid: {}'.format(os.getpid()))
        logger.debug("OEM code page: %s" % windll.kernel32.GetOEMCP())
        logger.debug("ANSI code page: %s" % windll.kernel32.GetACP())
        logger.debug("Console output code page: %s" % windll.kernel32.GetConsoleOutputCP())
        if cp:
            logger.debug("Setting console output code page to %s" % cp)
            try:
                win32console.SetConsoleOutputCP(cp)
            except Exception as e:
                logger.info(e)
            else:
                logger.info("Console output code page: %s" % windll.kernel32.GetConsoleOutputCP())
        logger.info('Spawning %s' % path)
        try:
            try:
                consout = self.getConsoleOut()
                self.initConsole(consout)

                si = win32process.GetStartupInfo()
                self.__childProcess, _, childPid, self.__tid = win32process.CreateProcess(None, path, None, None, False,
                                                                             0, None, None, si)
                logger.info('childPid: {}  host_pid: {}'.format(childPid, pid))
            except Exception:
                logger.info(traceback.format_exc())
                time.sleep(.1)
                win32api.PostThreadMessage(int(tid), win32con.WM_USER, 0, 0)
                sys.exit()

            time.sleep(.1)

            win32api.PostThreadMessage(int(tid), win32con.WM_USER, childPid, 0)

            parent = win32api.OpenProcess(win32con.PROCESS_TERMINATE | win32con.PROCESS_QUERY_INFORMATION , 0, int(pid))
            paused = False

            while True:
                consinfo = consout.GetConsoleScreenBufferInfo()
                cursorPos = consinfo['CursorPosition']

                if win32process.GetExitCodeProcess(parent) != win32con.STILL_ACTIVE or win32process.GetExitCodeProcess(self.__childProcess) != win32con.STILL_ACTIVE:
                    time.sleep(.1)
                    try:
                        win32process.TerminateProcess(self.__childProcess, 0)
                    except pywintypes.error as e:
                        # 'Access denied' happens always? Perhaps if not
                        # running as admin (or UAC enabled under Vista/7).
                        # Don't log. Child process will exit regardless when
                        # calling sys.exit
                        if e.args[0] != winerror.ERROR_ACCESS_DENIED:
                            logger.info(e)
                    logger.info('Exiting...')
                    sys.exit()

                if cursorPos.Y > maxconsoleY and not paused:
                    self.suspendThread()
                    paused = True

                if cursorPos.Y <= maxconsoleY and paused:
                    self.resumeThread()
                    paused = False

                time.sleep(.1)
        except Exception as e:
            logger.info(e)
            time.sleep(.1)


    def handler(self, sig):
        logger.info(sig)
        return False

    def getConsoleOut(self):
        consout = win32file.CreateFile('CONOUT$',
                                       win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                       win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                                       None,
                                       win32con.OPEN_EXISTING,
                                       0,
                                       0)

        return win32console.PyConsoleScreenBufferType(consout)

    def initConsole(self, consout):
        rect = win32console.PySMALL_RECTType(0, 0, 79, 24)
        consout.SetConsoleWindowInfo(True, rect)
        size = win32console.PyCOORDType(80, 16000)
        consout.SetConsoleScreenBufferSize(size)
        pos = win32console.PyCOORDType(0, 0)
        # Use NUL as fill char because it displays as whitespace
        # (if we interact() with the child)
        consout.FillConsoleOutputCharacter(screenbufferfillchar, size.X * size.Y, pos)

    def suspendThread(self):
        """Pauses the main thread of the child process."""

        handle = windll.kernel32.OpenThread(win32con.THREAD_SUSPEND_RESUME, 0, self.__tid)
        win32process.SuspendThread(handle)

    def resumeThread(self):
        """Un-pauses the main thread of the child process."""

        handle = windll.kernel32.OpenThread(win32con.THREAD_SUSPEND_RESUME, 0, self.__tid)
        win32process.ResumeThread(handle)

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

        ss =  [ (ns[0],'    %d: "%s"' % ns) for ns in self._strings ]
        ss.append((-1,'searcher_string:'))
        if self.eof_index >= 0:
            ss.append ((self.eof_index,'    %d: EOF' % self.eof_index))
        if self.timeout_index >= 0:
            ss.append ((self.timeout_index,'    %d: TIMEOUT' % self.timeout_index))
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
                offset = -(freshlen+len(s))
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

        ss =  [ (n,'    %d: re.compile("%s")' % (n,str(s.pattern))) for n,s in self._searches]
        ss.append((-1,'searcher_re:'))
        if self.eof_index >= 0:
            ss.append ((self.eof_index,'    %d: EOF' % self.eof_index))
        if self.timeout_index >= 0:
            ss.append ((self.timeout_index,'    %d: TIMEOUT' % self.timeout_index))
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
            searchstart = max(0, len(buffer)-searchwindowsize)
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


def join_args(args):
    """Joins arguments into a command line. It quotes all arguments that contain
    spaces or any of the characters ^!$%&()[]{}=;'+,`~"""
    commandline = []
    for arg in args:
        if re.search('[\^!$%&()[\]{}=;\'+,`~\s]', arg):
            arg = '"%s"' % arg
        commandline.append(arg)
    return ' '.join(commandline)

def split_command_line(command_line, escape_char = '^'):
    """This splits a command line into a list of arguments. It splits arguments
    on spaces, but handles embedded quotes, doublequotes, and escaped
    characters. It's impossible to do this with a regular expression, so I
    wrote a little state machine to parse the command line. """

    arg_list = []
    arg = ''

    # Constants to name the states we can be in.
    state_basic = 0
    state_esc = 1
    state_singlequote = 2
    state_doublequote = 3
    state_whitespace = 4 # The state of consuming whitespace between commands.
    state = state_basic

    for c in command_line:
        if state == state_basic or state == state_whitespace:
            if c == escape_char: # Escape the next character
                state = state_esc
            elif c == r"'": # Handle single quote
                state = state_singlequote
            elif c == r'"': # Handle double quote
                state = state_doublequote
            elif c.isspace():
                # Add arg to arg_list if we aren't in the middle of whitespace.
                if state == state_whitespace:
                    None # Do nothing.
                else:
                    arg_list.append(arg)
                    arg = ''
                    state = state_whitespace
            else:
                arg = arg + c
                state = state_basic
        elif state == state_esc:
            arg = arg + c
            state = state_basic
        elif state == state_singlequote:
            if c == r"'":
                state = state_basic
            else:
                arg = arg + c
        elif state == state_doublequote:
            if c == r'"':
                state = state_basic
            else:
                arg = arg + c

    if arg != '':
        arg_list.append(arg)
    return arg_list
