# -*- coding: utf-8 -*-

from typing import BinaryIO, Union, Optional, Dict, TextIO
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
    EOL: int = ord('\n')
    eofSym: int = 0
    maxT: int = 44
    noSym: int = 44

    buffer: Buffer    # scanner buffer
    t: Token          # current token
    ch: int           # current input character
    pos: int          # byte position of current character
    char_pos: int     # position by unicode characters starting with 0
    col: int          # column number of current character
    line: int         # line number of current character
    old_eols: int     # EOLs that appeared in a comment;

    start: Dict[int, int]  # maps initial token character to start state
    literals: dict         # maps literal strings to literal kinds

    tokens: Token     # list of tokens already peeked (first token is a dummy)
    pt: Token         # current peek token

    tval: str         # token text used in NextToken(), dynamically enlarged

    def init(self):
        self.start = dict()
        self.literals = dict()

        for i in range(65, 91):
            self.start[i] = 1

        self.start[95] = 1

        for i in range(97, 123):
            self.start[i] = 1

        for i in range(48, 58):
            self.start[i] = 2

        self.start[34] = 12
        self.start[39] = 5
        self.start[36] = 13
        self.start[61] = 16
        self.start[46] = 33
        self.start[43] = 17
        self.start[45] = 18
        self.start[60] = 34
        self.start[94] = 20
        self.start[62] = 21
        self.start[44] = 22
        self.start[91] = 25
        self.start[93] = 26
        self.start[124] = 27
        self.start[40] = 35
        self.start[41] = 28
        self.start[123] = 29
        self.start[125] = 30
        self.start[Buffer.EOF] = -1
        
        self.literals["COMPILER"] = 6
        self.literals["IGNORECASE"] = 7
        self.literals["CHARACTERS"] = 8
        self.literals["TOKENS"] = 9
        self.literals["PRAGMAS"] = 10
        self.literals["COMMENTS"] = 11
        self.literals["FROM"] = 12
        self.literals["TO"] = 13
        self.literals["NESTED"] = 14
        self.literals["IGNORE"] = 15
        self.literals["PRODUCTIONS"] = 16
        self.literals["END"] = 19
        self.literals["ANY"] = 23
        self.literals["out"] = 26
        self.literals["WEAK"] = 34
        self.literals["SYNC"] = 39
        self.literals["IF"] = 40
        self.literals["CONTEXT"] = 41

        self.pos = self.char_pos = -1
        self.col = self.old_eols = 0
        self.line = 1

        self.next_ch()

        if self.ch == 0xEF:  # check optional byte order mark for UTF-8
            self.next_ch()
            ch1 = self.ch
            self.next_ch()
            ch2 = self.ch

            if ch1 != 0xBB or ch2 != 0xBF:
                raise FatalError("Illegal byte order mark at start of file")

            self.buffer = UTF8Buffer(self.buffer)
            self.col = 0
            self.char_pos = -1
            self.next_ch()

        self.pt = self.tokens = Token()

    def __init__(self, s: Union[str, BinaryIO]):
        self.buffer = Buffer(s)
        self.init()

    def next_ch(self):
        if self.old_eols > 0:
            self.ch = self.EOL
            self.old_eols -= 1
            return

        self.pos = self.buffer.get_pos()
        # buffer reads unicode chars, if UTF8 has been detected
        self.ch = self.buffer.read()
        self.col += 1
        self.char_pos += 1
        # replace isolated '\r' by '\n' in order to make
        # eol handling uniform across Windows, Unix and Mac
        if self.ch == ord('\r') and self.buffer.peek() != ord('\n'):
            self.ch = self.EOL

        if self.ch == self.EOL:
            self.line += 1
            self.col = 0

    def add_ch(self):
        if self.ch != Buffer.EOF:
            self.tval += chr(self.ch)
            self.next_ch()

    def comment0(self) -> bool:
        level = 1
        pos0 = self.pos
        line0 = self.line
        col0 = self.col
        char_pos0 = self.char_pos

        self.next_ch()
        if self.ch == ord('/'):
            self.next_ch()
            while True:
                if self.ch == ord('\n'):
                    level -= 1
                    if level == 0:
                        self.old_eols = self.line - line0
                        self.next_ch()
                        return True
                    self.next_ch()

                elif self.ch == Buffer.EOF:
                    return False

                else:
                    self.next_ch()
        else:
            self.buffer.set_pos(pos0)
            self.next_ch()
            self.line = line0
            self.col = col0
            self.char_pos = char_pos0
        return False

    def comment1(self) -> bool:
        level = 1
        pos0 = self.pos
        line0 = self.line
        col0 = self.col
        char_pos0 = self.char_pos

        self.next_ch()
        if self.ch == ord('*'):
            self.next_ch()
            while True:
                if self.ch == ord('*'):
                    self.next_ch()
                    if self.ch == ord('/'):
                        level -= 1
                        if level == 0:
                            self.old_eols = self.line - line0
                            self.next_ch()
                            return True
                        self.next_ch()
                elif self.ch == ord('/'):
                    self.next_ch()
                    if self.ch == ord('*'):
                        level += 1
                        self.next_ch()
                elif self.ch == Buffer.EOF:
                    return False
                else:
                    self.next_ch()
        else:
            self.buffer.set_pos(pos0)
            self.next_ch()
            self.line = line0
            self.col = col0
            self.char_pos = char_pos0
        return False

