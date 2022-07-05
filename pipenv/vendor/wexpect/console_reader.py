"""Wexpect is a Windows variant of pexpect https://pexpect.readthedocs.io.

Wexpect is a Python module for spawning child applications and controlling
them automatically.

console_reader Implements a virtual terminal, and starts the child program.
The main wexpect.spawn class connect to this class to reach the child's terminal.
"""

import time
import logging
import os
import traceback
import psutil
from io import StringIO

import ctypes
from ctypes import windll
import win32console
import win32process
import win32con
import win32file
import win32gui
import win32pipe
import socket

from .wexpect_util import init_logger
from .wexpect_util import EOF_CHAR
from .wexpect_util import SIGNAL_CHARS

#
# System-wide constants
#
screenbufferfillchar = '\4'
maxconsoleY = 8000
default_port = 4321

#
# Create logger: We write logs only to file. Printing out logs are dangerous, because of the deep
# console manipulation.
#
logger = logging.getLogger('wexpect')


class ConsoleReaderBase:
    """Consol class (aka. client-side python class) for the child.

    This class initialize the console starts the child in it and reads the console periodically.
    """

    def __init__(self, path, host_pid, codepage=None, window_size_x=80, window_size_y=25,
                 buffer_size_x=80, buffer_size_y=16000, local_echo=True, interact=False, **kwargs):
        """Initialize the console starts the child in it and reads the console periodically.

        Args:
            path (str): Child's executable with arguments.
            parent_pid (int): Parent (aka. host) process process-ID
            codepage (:obj:, optional): Output console code page.
        """
        self.lastRead = 0
        self.__bufferY = 0
        self.lastReadData = ""
        self.totalRead = 0
        self.__buffer = StringIO()
        self.__currentReadCo = win32console.PyCOORDType(0, 0)
        self.pipe = None
        self.connection = None
        self.consin = None
        self.consout = None
        self.local_echo = local_echo
        self.console_pid = os.getpid()
        self.host_pid = host_pid
        self.host_process = psutil.Process(host_pid)
        self.child_process = None
        self.child_pid = None
        self.enable_signal_chars = True

        logger.info(f'ConsoleReader started. location {os.path.abspath(__file__)}')

        if codepage is None:
            codepage = windll.kernel32.GetACP()

        try:
            logger.info("Setting console output code page to %s" % codepage)
            win32console.SetConsoleOutputCP(codepage)
            logger.info(
                "Console output code page: %s" % ctypes.windll.kernel32.GetConsoleOutputCP())
        except Exception as e: # pragma: no cover
            # I hope this code is unreachable...
            logger.error(e)

        try:
            self.create_connection(**kwargs)
            logger.info('Spawning %s' % path)
            try:
                self.initConsole()
                si = win32process.GetStartupInfo()
                self.__childProcess, _, self.child_pid, self.child_tid = win32process.CreateProcess(
                    None, path, None, None, False, 0, None, None, si)
                self.child_process = psutil.Process(self.child_pid)

                logger.info(f'Child pid: {self.child_pid}  Console pid: {self.console_pid}')

            except Exception: # pragma: no cover
                # I hope this code is unreachable...
                logger.error(traceback.format_exc())
                return

            if interact:
                self.interact()
                self.interact()

            self.read_loop()
        except Exception: # pragma: no cover
            # I hope this code is unreachable...
            logger.error(traceback.format_exc())
        finally:
            try:
                self.terminate_child()
                time.sleep(.01)
                self.send_to_host(self.readConsoleToCursor())
                self.sendeof()
                time.sleep(.1)
                self.close_connection()
                logger.info('Console finished.')
            except Exception: # pragma: no cover
                # I hope this code is unreachable...
                logger.error(traceback.format_exc())

    def read_loop(self):

        while True:
            if not self.isalive(self.host_process):
                logger.info('Host process has been died.')
                return

            self.child_exitstatus = win32process.GetExitCodeProcess(self.__childProcess)
            if self.child_exitstatus != win32con.STILL_ACTIVE:
                logger.info(f'Child finished with code: {self.child_exitstatus}')
                return

            consinfo = self.consout.GetConsoleScreenBufferInfo()
            cursorPos = consinfo['CursorPosition']

            if cursorPos.Y > maxconsoleY:
                '''If the console output becomes long, we suspend the child, read all output then
                clear the console before we resume the child.
                '''
                logger.info('cursorPos %s' % cursorPos)
                self.suspend_child()
                time.sleep(.2)
                self.send_to_host(self.readConsoleToCursor())
                self.refresh_console()
                self.resume_child()
            else:
                self.send_to_host(self.readConsoleToCursor())

            s = self.get_from_host()
            if s:
                logger.debug(f'get_from_host: {s}')
            else:
                logger.spam(f'get_from_host: {s}')
            if self.enable_signal_chars:
                for sig, char in SIGNAL_CHARS.items():
                    if char in s:
                        self.child_process.send_signal(sig)
            s = s.decode()
            self.write(s)


            time.sleep(.02)

    def suspend_child(self):
        """Pauses the main thread of the child process."""
        handle = windll.kernel32.OpenThread(win32con.THREAD_SUSPEND_RESUME, 0, self.child_tid)
        win32process.SuspendThread(handle)

    def resume_child(self):
        """Un-pauses the main thread of the child process."""
        handle = windll.kernel32.OpenThread(win32con.THREAD_SUSPEND_RESUME, 0, self.child_tid)
        win32process.ResumeThread(handle)

    def refresh_console(self):
        """Clears the console after pausing the child and
        reading all the data currently on the console."""

        orig = win32console.PyCOORDType(0, 0)
        self.consout.SetConsoleCursorPosition(orig)
        self.__currentReadCo.X = 0
        self.__currentReadCo.Y = 0
        writelen = self.__consSize.X * self.__consSize.Y
        # Use NUL as fill char because it displays as whitespace
        # (if we interact() with the child)
        self.consout.FillConsoleOutputCharacter(screenbufferfillchar, writelen, orig)

        self.__bufferY = 0
        self.__buffer.truncate(0)

    def terminate_child(self):
        try:
            if self.child_process:
                self.child_process.kill()
        except psutil.NoSuchProcess:
            logger.info('The process has already died.')
        return

    def isalive(self, process):
        """True if the child is still alive, false otherwise"""
        try:
            self.exitstatus = process.wait(timeout=0)
            return False
        except psutil.TimeoutExpired:
            return True

    def write(self, s):
        """Writes input into the child consoles input buffer."""

        if len(s) == 0:
            return 0
        if s[-1] == '\n':
            s = s[:-1]
        records = [self.createKeyEvent(c) for c in str(s)]
        if not self.consout:
            return ""

        # Store the current cursor position to hide characters in local echo disabled mode
        # (workaround).
        consinfo = self.consout.GetConsoleScreenBufferInfo()
        startCo = consinfo['CursorPosition']

        # Send the string to console input
        wrote = self.consin.WriteConsoleInput(records)

        # Wait until all input has been recorded by the console.
        ts = time.time()
        while self.consin.PeekConsoleInput(8) != ():
            if time.time() > ts + len(s) * .1 + .5:
                break
            time.sleep(.05)

        # Hide characters in local echo disabled mode (workaround).
        if not self.local_echo:
            self.consout.FillConsoleOutputCharacter(screenbufferfillchar, len(s), startCo)

        return wrote

    def createKeyEvent(self, char):
        """Creates a single key record corrosponding to
            the ascii character char."""

        evt = win32console.PyINPUT_RECORDType(win32console.KEY_EVENT)
        evt.KeyDown = True
        evt.Char = char
        evt.RepeatCount = 1
        return evt

    def initConsole(self, consout=None, window_size_x=80, window_size_y=25, buffer_size_x=80,
                    buffer_size_y=16000):
        if not consout:
            consout = self.getConsoleOut()

        self.consin = win32console.GetStdHandle(win32console.STD_INPUT_HANDLE)

        rect = win32console.PySMALL_RECTType(0, 0, window_size_x - 1, window_size_y - 1)
        consout.SetConsoleWindowInfo(True, rect)
        size = win32console.PyCOORDType(buffer_size_x, buffer_size_y)
        consout.SetConsoleScreenBufferSize(size)
        pos = win32console.PyCOORDType(0, 0)
        # Use NUL as fill char because it displays as whitespace
        # (if we interact() with the child)
        consout.FillConsoleOutputCharacter(screenbufferfillchar, size.X * size.Y, pos)

        consinfo = consout.GetConsoleScreenBufferInfo()
        self.__consSize = consinfo['Size']
        logger.info('self.__consSize: ' + str(self.__consSize))
        self.startCursorPos = consinfo['CursorPosition']

    def parseData(self, s):
        """Ensures that special characters are interpretted as
        newlines or blanks, depending on if there written over
        characters or screen-buffer-fill characters."""

        strlist = []
        for i, c in enumerate(s):
            if c == screenbufferfillchar:
                if (self.totalRead - self.lastRead + i + 1) % self.__consSize.X == 0:
                    strlist.append('\r\n')
            else:
                strlist.append(c)

        s = ''.join(strlist)
        return s

    def getConsoleOut(self):
        consfile = win32file.CreateFile(
            'CONOUT$',
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None,
            win32con.OPEN_EXISTING,
            0,
            0)

        self.consout = win32console.PyConsoleScreenBufferType(consfile)
        return self.consout

    def getCoord(self, offset):
        """Converts an offset to a point represented as a tuple."""

        x = offset % self.__consSize.X
        y = offset // self.__consSize.X
        return win32console.PyCOORDType(x, y)

    def getOffset(self, coord):
        """Converts a tuple-point to an offset."""

        return coord.X + coord.Y * self.__consSize.X

    def readConsole(self, startCo, endCo):
        """Reads the console area from startCo to endCo and returns it
        as a string."""

        if startCo is None:
            startCo = self.startCursorPos
            startCo.Y = startCo.Y

        if endCo is None:
            consinfo = self.consout.GetConsoleScreenBufferInfo()
            endCo = consinfo['CursorPosition']
            endCo = self.getCoord(0 + self.getOffset(endCo))

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

            s = self.consout.ReadConsoleOutputCharacter(readlen, startCo)
            self.lastRead += len(s)
            self.totalRead += len(s)
            buff.append(s)

            startCo = endPoint

        return ''.join(buff)

    def readConsoleToCursor(self):
        """Reads from the current read position to the current cursor
        position and inserts the string into self.__buffer."""

        if not self.consout:
            return ""

        consinfo = self.consout.GetConsoleScreenBufferInfo()
        cursorPos = consinfo['CursorPosition']

        logger.spam('cursor: %r, current: %r' % (cursorPos, self.__currentReadCo))

        isSameX = cursorPos.X == self.__currentReadCo.X
        isSameY = cursorPos.Y == self.__currentReadCo.Y
        isSamePos = isSameX and isSameY

        logger.spam('isSameY: %r' % isSameY)
        logger.spam('isSamePos: %r' % isSamePos)

        if isSameY or not self.lastReadData.endswith('\r\n'):
            # Read the current slice again
            self.totalRead -= self.lastRead
            self.__currentReadCo.X = 0
            self.__currentReadCo.Y = self.__bufferY

        logger.spam('cursor: %r, current: %r' % (cursorPos, self.__currentReadCo))

        raw = self.readConsole(self.__currentReadCo, cursorPos)
        rawlist = []
        while raw:
            rawlist.append(raw[:self.__consSize.X])
            raw = raw[self.__consSize.X:]
        raw = ''.join(rawlist)
        s = self.parseData(raw)
        for i, line in enumerate(reversed(rawlist)):
            if line.endswith(screenbufferfillchar):
                # Record the Y offset where the most recent line break was detected
                self.__bufferY += len(rawlist) - i
                break

        logger.spam('lastReadData: %r' % self.lastReadData)
        if s:
            logger.debug('Read: %r' % s)
        else:
            logger.spam('Read: %r' % s)

        if isSamePos and self.lastReadData == s:
            logger.spam('isSamePos and self.lastReadData == s')
            s = ''

        if s:
            lastReadData = self.lastReadData
            pos = self.getOffset(self.__currentReadCo)
            self.lastReadData = s
            if isSameY or not lastReadData.endswith('\r\n'):
                # Detect changed lines
                self.__buffer.seek(pos)
                buf = self.__buffer.read()
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
            self.__buffer.seek(pos)
            self.__buffer.truncate()
            self.__buffer.write(raw)

        self.__currentReadCo.X = cursorPos.X
        self.__currentReadCo.Y = cursorPos.Y

        return s

    def interact(self):
        """Displays the child console for interaction."""

        logger.debug('Start interact window')
        win32gui.ShowWindow(win32console.GetConsoleWindow(), win32con.SW_SHOW)

    def sendeof(self):
        """This sends an EOF to the host. This sends a character which inform the host that child
        has been finished, and all of it's output has been send to host.
        """

        self.send_to_host(EOF_CHAR)


class ConsoleReaderSocket(ConsoleReaderBase):

    def create_connection(self, **kwargs):
        try:
            self.port = kwargs['port']
            # Create a TCP/IP socket
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_address = ('localhost', self.port)
            self.sock.bind(server_address)
            logger.info(f'Socket started at port: {self.port}')

            # Listen for incoming connections
            self.sock.settimeout(5)
            self.sock.listen(1)
            self.connection, client_address = self.sock.accept()
            self.connection.settimeout(.01)
            logger.info(f'Client connected: {client_address}')
        except Exception as e:  # pragma: no cover
            # I hope this code is unreachable.
            logger.error(f"Port: {self.port} {e}")
            raise

    def close_connection(self):
        if self.connection:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            self.connection = None

    def send_to_host(self, msg):
        # convert to bytes
        if isinstance(msg, str):
            msg = str.encode(msg)
        if msg:
            logger.debug(f'Sending msg: {msg}')
        else:
            logger.spam(f'Sending msg: {msg}')
        self.connection.sendall(msg)

    def get_from_host(self):
        try:
            msg = self.connection.recv(4096)
        except socket.timeout as e:
            err = e.args[0]
            # this next if/else is a bit redundant, but illustrates how the
            # timeout exception is setup
            if err == 'timed out':
                logger.debug('recv timed out, retry later')
                return b''
            else:
                raise
        else:
            if len(msg) == 0:
                raise Exception('orderly shutdown on server end')
            else:
                # got a message do something :)
                return msg


class ConsoleReaderPipe(ConsoleReaderBase):
    def create_connection(self, **kwargs):
        pipe_name = 'wexpect_{}'.format(self.console_pid)
        pipe_full_path = r'\\.\pipe\{}'.format(pipe_name)
        logger.info('Start pipe server: %s', pipe_full_path)
        self.pipe = win32pipe.CreateNamedPipe(
            pipe_full_path,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
            1, 65536, 65536, 0, None)
        logger.info("waiting for client")
        win32pipe.ConnectNamedPipe(self.pipe, None)
        logger.info('got client')

    def close_connection(self):
        if self.pipe:
            win32file.CloseHandle(self.pipe)

    def send_to_host(self, msg):
        # convert to bytes
        if isinstance(msg, str):
            msg = str.encode(msg)
        if msg:
            logger.debug(f'Sending msg: {msg}')
        else:
            logger.spam(f'Sending msg: {msg}')
        win32file.WriteFile(self.pipe, msg)

    def get_from_host(self):
        data, avail, bytes_left = win32pipe.PeekNamedPipe(self.pipe, 4096)
        logger.spam(f'data: {data}  avail:{avail}  bytes_left{bytes_left}')
        if avail > 0:
            resp = win32file.ReadFile(self.pipe, 4096)
            ret = resp[1]
            return ret
        else:
            return b''
