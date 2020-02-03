# -*- coding: utf-8 -*-

from typing import BinaryIO, Union, Optional
import os

from .constants import COCO_WCHAR_MAX
from .errors import FatalError


class Token:
    kind: int      # token kind
    pos: int       # token position in bytes in the source text (starting at 0)
    charPos: int   # token position in characters in the source text (starting at 0)
    col: int       # token column (starting at 1)
    line: int      # token line (starting at 1)
    val: str       # token value
    next: 'Token'  # ML 2005-03-11 Peek tokens are kept in linked list


# -----------------------------------------------------------------------------------
# Buffer
# -----------------------------------------------------------------------------------
class Buffer:
    """ This Buffer supports the following cases:
    1) seekable stream (file)
        a) whole stream in buffer
        b) part of stream in buffer
    2) non seekable stream (network, console)
    """
    EOF: int = COCO_WCHAR_MAX + 1
    MIN_BUFFER_LENGTH: int = 1024  # 1KB
    MAX_BUFFER_LENGTH: int = MIN_BUFFER_LENGTH * 64  # 64 KB
    buf: bytearray  # input buffer
    buf_start: int  # position of first byte in buffer relative to input stream
    buf_len: int    # length of buffer
    file_len: int   # length of input stream (may change if stream is no file)
    buf_pos: int    # current position in buffer
    file: Optional[BinaryIO]  # input stream (seekable)
    stream: BinaryIO  # growing input stream (e.g.: console, network)

    def __init__(self, s: Union[str, BinaryIO, 'Buffer']):
        assert isinstance(s, (str, BinaryIO, Buffer))
        if isinstance(s, BinaryIO):
            self.stream = s
            self.file_len = self.buf_len = self.buf_start = self.buf_pos = 0
            self.buf = bytearray(self.MIN_BUFFER_LENGTH)
        elif isinstance(s, str):
            try:
                self.file_len = os.path.getsize(s)
                self.file = open(s, "rb")
                self.buf_len = min(self.file_len, self.MAX_BUFFER_LENGTH)
                self.buf = bytearray(self.buf_len)
                self.buf_start = (2 << 31) - 1  # nothing in buffer so far

                if self.file_len > 0:
                    self.set_pos(0)   # setup buffer to position 0 (start)
                else:
                    self.buf_pos = 0  # index 0 is already after the file, thus setPos(0) is invalid

                if self.buf_len == self.file_len:
                    self.close()
            except OSError:
                raise FatalError("Could not open file {}".format(s))
        else:
            self.buf = s.buf
            self.buf_start = s.buf_start
            self.buf_len = s.buf_len
            self.file_len = s.file_len
            self.buf_pos = s.buf_pos
            self.file = s.file
            self.stream = s.stream
            # prevent finalize from closing the file
            s.file = None

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None

    def read(self) -> int:
        if self.buf_pos < self.buf_len:
            pass
        elif self.get_pos() < self.file_len:
            self.set_pos(self.get_pos())
        elif self.stream is not None and self.read_next_stream_chunk() > 0:
            pass
        else:
            return self.EOF

        result = self.buf[self.buf_pos] & 0xFF
        self.buf_pos += 1
        return result

    def peek(self) -> int:
        cur_pos: int = self.get_pos()
        ch: int = self.read()
        self.set_pos(cur_pos)
        return ch

    def get_string(self, beg: int, end: int) -> str:
        buf = bytearray()
        old_pos = self.get_pos()
        self.set_pos(beg)
        while self.get_pos() < end:
            buf.append(self.read())
        self.set_pos(old_pos)
        return buf.decode('utf-8')

    def get_pos(self) -> int:
        return self.buf_pos + self.buf_start

    def set_pos(self, value: int):
        if value >= self.file_len and self.stream is not None:
            # Wanted position is after buffer and the stream
            # is not seek-able e.g. network or console,
            # thus we have to read the stream manually till
            # the wanted position is in sight.
            while value >= self.file_len and self.read_next_stream_chunk() > 0:
                pass

        if value < 0 or value > self.file_len:
            raise FatalError("buffer out of bounds access, position: {}".format(value))

        if self.buf_start <= value < self.buf_start + self.buf_len:  # already in buffer
            self.buf_pos = value - self.buf_start
        elif self.file is not None:  # must be swapped in
            try:
                self.file.seek(value)
                self.buf = bytearray(self.file.read(len(self.buf)))
                self.buf_len = len(self.buf)
                self.buf_start = value
                self.buf_pos = 0
            except OSError as e:
                raise FatalError(e.strerror)
        else:
            self.buf_pos = self.file_len - self.buf_start

    def read_next_stream_chunk(self) -> int:
        free = len(self.buf) - self.buf_len
        if free == 0:
            # in the case of a growing input stream
            # we can neither seek in the stream, nor can we
            # foresee the maximum length, thus we must adapt
            # the buffer size on demand.
            newbuf = bytearray(self.buf_len * 2)
            newbuf[0: self.buf_len] = self.buf
            self.buf = newbuf
            free = self.buf_len

        try:
            tmp: bytearray = bytearray(self.stream.read(free))
            self.buf[self.buf_len:] = tmp
        except OSError as e:
            raise FatalError(e.strerror)

        if tmp:
            self.file_len = self.buf_len = (self.buf_len + len(tmp))

        return len(tmp)


class UTF8Buffer(Buffer):
    def __init__(self, b: Buffer):
        super().__init__(b)

    def read(self) -> int:
        ch: int = 0xFF
        while (ch >= 128) and ((ch & 0xC0) != 0xC0) and (ch != self.EOF):
            ch = super().read()

        if ch < 128 or ch == self.EOF:
            # nothing to do, first 127 chars are the same in ascii and utf8
            # 0xxxxxxx or end of file character
            pass
        elif ch & 0xF0 == 0xF0:
            # 11110xxx 10xxxxxx 10xxxxxx 10xxxxxx
            c1 = ch & 0x07
            ch = super().read()
            c2 = ch & 0x3F
            ch = super().read()
            c3 = ch & 0x3F
            ch = super().read()
            c4 = ch & 0x3F
            ch = (((((c1 << 6) | c2) << 6) | c3) << 6) | c4
        elif ch & 0xE0 == 0xE0:
            # 1110xxxx 10xxxxxx 10xxxxxx
            c1 = ch & 0x0F
            ch = super().read()
            c2 = ch & 0x3F
            ch = super().read()
            c3 = ch & 0x3F
            ch = (((c1 << 6) | c2) << 6) | c3
        elif ch & 0xC0 == 0xC0:
            c1 = ch & 0x1F
            ch = super().read()
            c2 = ch & 0x3F
            ch = (c1 << 6) | c2

        return ch


class Scanner:
    EOL: str = '\n'
    eofSym: int = 0
    maxT: int = 44
    noSym: int = 44
