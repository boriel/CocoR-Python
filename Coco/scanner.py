# -*- coding: utf-8 -*-

from typing import BinaryIO, Union, Dict

from .errors import FatalError
from .buffer import Buffer, UTF8Buffer


class Token:
    kind: int      # token kind
    pos: int       # token position in bytes in the source text (starting at 0)
    charPos: int   # token position in characters in the source text (starting at 0)
    col: int       # token column (starting at 1)
    line: int      # token line (starting at 1)
    val: str       # token value
    next: 'Token'  # ML 2005-03-11 Peek tokens are kept in linked list


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

    def check_literal(self):
        val = self.t.val
        kind = self.literals.get(val)
        if kind is not None:
            self.t.kind = kind

    def next_token(self) -> Token:
        while self.ch in (ord(' '), 9, 10, 13):
            self.next_ch()

        if self.ch == ord('/') and (self.comment0() or self.comment1()):
            return self.next_token()

        rec_kind = self.noSym

        self.t = Token()
        self.t.pos = self.pos
        self.t.col = self.col
        self.t.line = self.line
        self.t.charPos = self.char_pos

        state: int = self.start.get(self.ch, 0)
        self.tval = ''
        self.add_ch()

        while True:
            ch: str = chr(self.ch)
            if state == -1:
                self.t.kind = self.eofSym
                break

            elif state == 0:
                if rec_kind != self.noSym:
                    self.set_scanner_behind_T()
                self.t.kind = rec_kind
                break

            elif state == 1:
                rec_kind = 1
                if ch.isalnum() or ch == '_':
                    self.add_ch()
                    state = 1
                else:
                    self.t.kind = 1
                    self.t.val = self.tval
                    self.check_literal()
                    return self.t

            elif state == 2:
                rec_kind = 2
                if ch.isnumeric():
                    self.add_ch()
                    state = 2

            elif state == 3:
                self.t.kind = 3
                break

            elif state == 4:
                self.t.kind = 4
                break

            elif state == 5:
                if self.ch <= 9 or self.ch in (11, 12) or 14 <= self.ch <= ord('&') or '(' <= ch <= '[' or \
                        ch >= ']' and self.ch <= 65535:
                    self.add_ch()
                    state = 6
                elif self.ch == 92:
                    self.add_ch()
                    state = 7
                else:
                    state = 0

            elif state == 6:
                if self.ch == 39:
                    self.add_ch()
                    state = 9
                else:
                    state = 0

            elif state == 7:
                if ' ' <= ch <= '~':
                    self.add_ch()
                    state = 8
                else:
                    state = 0

            elif state == 8:
                if '0' <= ch <= '9' or 'a' <= ch <= 'f':
                    self.add_ch()
                elif state == 39:
                    self.add_ch()
                    state = 9
                else:
                    state = 0

            elif state == 9:
                self.t.kind = 5
                break

            elif state == 10:
                rec_kind = 45
                if ch.isalnum() or ch == '_':
                    self.add_ch()
                    state = 10
                else:
                    self.t.kind = 45
                    break

            elif state == 11:
                rec_kind = 46
                if '-' <= ch <= '.' or '0' <= ch <= ':' or ch.isalpha() or ch == '_':
                    self.add_ch()
                else:
                    self.t.kind = 46
                    break

            elif state == 12:
                if self.ch <= 9 or 11 <= self.ch <= 12 or self.ch >= 14 and ch <= '!' or '#' <= ch <= '[' or \
                        ch >= ']' and self.ch <= 65535:
                    self.add_ch()
                elif self.ch in (10, 13):
                    self.add_ch()
                    state = 4
                elif ch == '"':
                    self.add_ch()
                    state = 3
                elif self.ch == 92:
                    self.add_ch()
                    state = 14
                else:
                    state = 0

            elif state == 13:
                rec_kind = 45
                if ch.isnumeric():
                    self.add_ch()
                    state = 10
                elif ch == '_' or ch.isalpha():
                    self.add_ch()
                    state = 15
                else:
                    self.t.kind = 45
                    break

            elif state == 14:
                if ' ' <= ch <= '~':
                    self.add_ch()
                    state = 12
                else:
                    state = 0

            elif state == 15:
                rec_kind = 45
                if ch.isnumeric():
                    self.add_ch()
                    state = 10
                elif ch == '_' or ch.isalpha():
                    self.add_ch()
                elif ch == '=':
                    self.add_ch()
                    state = 11
                else:
                    self.t.kind = 45
                    break

            elif state == 16:
                self.t.kind = 17
                break

            elif state == 17:
                self.t.kind = 20
                break

            elif state == 18:
                self.t.kind = 21
                break

            elif state == 19:
                self.t.kind = 22
                break

            elif state == 20:
                self.t.kind = 25
                break

            elif state == 21:
                self.t.kind = 27
                break

            elif state == 22:
                self.t.kind = 28
                break

            elif state == 23:
                self.t.kind = 29
                break

            elif state == 24:
                self.t.kind = 30
                break

            elif state == 25:
                self.t.kind = 31
                break

            elif state == 26:
                self.t.kind = 32
                break

            elif state == 27:
                self.t.kind = 33
                break

            elif state == 28:
                self.t.kind = 36
                break

            elif state == 29:
                self.t.kind = 37
                break

            elif state == 30:
                self.t.kind = 38
                break

            elif state == 31:
                self.t.kind = 42
                break

            elif state == 32:
                self.t.kind = 43
                break

            elif state == 33:
                rec_kind = 18
                if ch == '.':
                    self.add_ch()
                    state = 19
                elif ch == '>':
                    self.add_ch()
                    state = 24
                elif ch == ')':
                    self.add_ch()
                    state = 32
                else:
                    self.t.kind = 18
                    break

            elif state == 34:
                rec_kind = 24
                if ch == '.':
                    self.add_ch()
                    state = 23
                else:
                    self.t.kind = 24
                    break

            elif state == 35:
                rec_kind = 35
                if ch == '.':
                    self.add_ch()
                    state = 31
                else:
                    self.t.kind = 35
                    break

        self.t.val = self.tval
        return self.t

    def set_scanner_behind_T(self):
        self.buffer.set_pos(self.t.pos)
        self.next_ch()
        self.line = self.t.line
        self.col = self.t.col
        self.char_pos = self.t.charPos

        for _ in self.tval:
            self.next_ch()

    def scan(self) -> Token:
        """ Get the next token (possibly a token already seen during peeking)
        """
        if self.tokens is None:
            return self.next_token()

        self.pt = self.tokens = self.tokens.next
        return self.tokens

    def peek(self) -> Token:
        """ Get the next token, ignore pragmas
        """
        while True:
            if self.pt.next is None:
                self.pt.next = self.next_token()

            self.pt = self.pt.next
            if self.pt.kind > self.maxT:
                continue  # skip pragmas

        return self.pt

    def reset_peek(self):
        """ Make sure that peeking starts at current scan position
        """
        self.pt = self.tokens
