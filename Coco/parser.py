# -*- coding: utf-8 -*-


from .errors import Errors
from .scanner import Scanner, Token
from .trace import Trace
from .tab import Tab, Position
from .dfa import DFA
from .charset import CharSet
from .parsergen import ParserGen


T_: bool = True
x_: bool = False


class Parser:
    _EOF: int = 0
    _ident: int = 1
    _number: int = 2
    _string: int = 3
    _badString: int = 4
    _char: int = 5
    maxT: int = 44
    _ddtSym: int = 45
    _optionSym: int = 46

    minErrDist = 2

    t: Token   # last recognized token
    la: Token  # lookahead token
    errDist: int = minErrDist

    scanner: Scanner
    errors: Errors

    id: int = 0
    str_: int = 1

    trace: Trace
    tab: Tab
    pgen: ParserGen
    dfa: DFA

    genScanner: bool
    tokenString: str          # used in declarations of literal tokens
    noString: str = "-none-"  # used in declarations of literal tokens

    def __init__(self, scanner: Scanner):
        self.scanner = scanner
        self.errors = Errors()

    def syn_err(self, n: int):
        if self.errDist >= self.minErrDist:
            self.errors.sym_err(self.la.line, self.la.col, n)
        self.errDist = 0

    def sem_err(self, msg: str):
        if self.errDist >= self.minErrDist:
            self.errors.sem_err(self.t.line, self.t.col, msg)
        self.errDist = 0

    def get(self):
        while True:
            self.t = self.la
            self.la = self.scanner.scan()
            if self.la.kind <= self.maxT:
                self.errDist += 1
                break

            if self.la.kind == 45:
                self.tab.set_DDT(self.la.val)

            if self.la.kind == 46:
                self.tab.set_option(self.la.val)

            self.la = self.t

    def expect(self, n: int):
        if self.la.kind == n:
            self.get()
        else:
            self.syn_err(n)

    def start_of(self, s: int) -> bool:
        return self.set_[s][self.la.kind]

    def expect_weak(self, n: int, follow: int):
        if self.la.kind == n:
            self.get()
        else:
            self.syn_err(n)
            while not self.start_of(follow):
                self.get()

    def weak_separator(self, n: int, sy_fol: int, rep_fol: int) -> bool:
        kind = self.la.kind
        if kind == n:
            self.get()
            return True
        elif self.start_of(rep_fol):
            return False

        self.syn_err(n)
        while not (self.set_[sy_fol][kind] or self.set_[rep_fol][kind] or self.set_[0][kind]):
            self.get()
            kind = self.la.kind

        return self.start_of(sy_fol)

    def coco(self):
        if self.start_of(1):
            self.get()
            beg = self.t.pos
            while self.start_of(1):
                self.get()

            self.pgen.using_pos = Position(beg, self.la.pos, 0)

        self.expect(6)
        self.genScanner = True
        self.tab.ignored = CharSet()
        self.expect(1)

        gram_name = self.t.val
        beg = self.la.pos

        while self.start_of(2):
            self.get()

        self.tab.semDeclPos = Position(beg, self.la.pos, 0)
        if self.la.kind == 7:
            self.get()
            self.dfa.ignore_case = True



    set_ = [
        [T_,T_,x_,T_, x_,T_,x_,x_, x_,x_,T_,T_, x_,x_,x_,T_, T_,T_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,T_,x_, x_,x_],
        [x_,T_,T_,T_, T_,T_,x_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, T_,T_,T_,x_, x_,x_,x_,x_, T_,T_,T_,x_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [T_,T_,x_,T_, x_,T_,x_,x_, x_,x_,T_,T_, x_,x_,x_,T_, T_,T_,T_,x_, x_,x_,x_,T_, x_,x_,x_,x_, x_,x_,x_,T_, x_,T_,T_,T_, x_,T_,x_,T_, T_,x_,T_,x_, x_,x_],
        [T_,T_,x_,T_, x_,T_,x_,x_, x_,x_,T_,T_, x_,x_,x_,T_, T_,T_,x_,T_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,T_,x_, x_,x_],
        [T_,T_,x_,T_, x_,T_,x_,x_, x_,x_,T_,T_, x_,x_,x_,T_, T_,T_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,T_,x_, x_,x_],
        [x_,T_,x_,T_, x_,T_,x_,x_, x_,x_,T_,T_, x_,x_,x_,T_, T_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,T_,x_, x_,x_],
        [x_,T_,x_,T_, x_,T_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,T_, x_,x_,x_,T_, x_,T_,x_,x_, x_,x_,x_,x_, x_,x_],
        [x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,T_, x_,T_,T_,T_, T_,x_,T_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, T_,x_,x_,x_, T_,x_,T_,x_, x_,x_,x_,x_, x_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,x_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_,x_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_,x_,x_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,x_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_,x_,T_, T_,T_,x_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,x_, T_,x_],
        [x_,T_,T_,T_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,x_,x_, T_,x_],
        [x_,T_,x_,T_, x_,T_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,T_,x_, x_,x_,x_,T_, x_,x_,x_,x_, x_,x_,x_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_,T_,x_, x_,x_],
        [x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,T_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, T_,x_,x_,x_, T_,x_,T_,x_, x_,x_,x_,x_, x_,x_],
        [x_,T_,x_,T_, x_,T_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,T_, x_,x_,x_,x_, x_,x_,x_,T_, x_,x_,T_,T_, x_,T_,x_,T_, T_,x_,T_,x_, x_,x_],
        [x_,T_,x_,T_, x_,T_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,T_, x_,x_,x_,x_, x_,x_,x_,T_, x_,x_,T_,T_, x_,T_,x_,T_, x_,x_,T_,x_, x_,x_],
        [x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,T_,x_, x_,x_,x_,x_, x_,x_,x_,x_, x_,x_,x_,x_, T_,T_,x_,x_, T_,x_,T_,x_, x_,x_,x_,x_, x_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,x_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,x_, x_,T_,T_,x_, T_,T_,T_,x_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,x_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_,x_,x_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, x_,T_,x_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, x_,T_,x_,x_, T_,T_,T_,x_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,x_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_,x_,T_, T_,T_,x_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, x_,T_,T_,T_, T_,T_,T_,T_, T_,x_],
        [x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, x_,T_,T_,T_, T_,T_,T_,T_, T_,T_,T_,T_, T_,x_]
    ]
