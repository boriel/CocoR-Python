# -*- coding: utf-8 -*-

import sys

from .errors import Errors
from .scanner import Scanner, Token
from .trace import Trace
from .tab import Tab, Position, Node, Graph, Symbol
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

        if self.la.kind == 8:
            self.get()
            while self.la.kind == 1:
                self.set_decl()

        if self.la.kind == 9:
            self.get()
            while self.la.kind in (1, 3, 5):
                self.token_decl(Node.t)

        if self.la.kind == 10:
            self.get()
            while self.la.kind in (1, 3, 5):
                self.token_decl(Node.pr)

        while self.la.kind == 11:
            self.get()
            nested: bool = False
            self.expect(12)
            g1 = self.token_expr()
            self.expect(13)
            g2 = self.token_expr()
            if self.la.kind == 14:
                self.get()
                nested = True

            self.dfa.new_comment(g1.l, g2.l, nested)

        while self.la.kind == 15:
            self.get()
            s = self.set()
            self.tab.ignored.or_(s)

        while self.la.kind not in (0, 16):
            self.syn_err(45)
            self.get()

        self.expect(16)
        if self.genScanner:
            self.dfa.make_deterministic()
        self.tab.delete_nodes()

        while self.la.kind == 1:
            self.get()
            sym: Symbol = self.tab.find_sym(self.t.val)
            undef: bool = sym is None
            if undef:
                sym = self.tab.new_sym(Node.nt, self.t.val, self.t.line)
            else:
                if sym.typ == Node.nt:
                    if sym.graph is not None:
                        self.sem_err("'{}' name declared twice".format(sym.name))
                else:
                    self.sem_err("this symbol kind not allowed on left side of production")
                sym.line = self.t.line

            no_attrs: bool = sym.attrPos is None
            sym.attrPos = None
            no_ret: bool = sym.retVar is None
            sym.retVar = None

            if self.la.kind in (24, 29):
                self.attr_decl(sym)

            if not undef:
                if no_attrs != (sym.attrPos is None) or no_ret != (sym.retVar is None):
                    self.sem_err("attribute mismatch between declaration and use of this symbol")

            if self.la.kind == 42:
                sym.semPos = self.sem_text()

            self.expect_weak(17, 3)
            g = self.expression()
            sym.graph = g.l
            self.tab.finish(g)
            self.expect_weak(18, 4)

        self.expect(19)
        self.expect(1)
        if gram_name != self.t.val:
            self.sem_err("'{}' name does not match grammar name".format(self.t.val))

        self.tab.gramSy = self.tab.find_sym(gram_name)
        if self.tab.gramSy is None:
            self.sem_err("missing production for grammar name")
        else:
            sym = self.tab.gramSy
            if sym.attrPos is not None:
                self.sem_err("grammar symbol must not have attributes")

        self.tab.noSym = self.tab.new_sym(Node.t, "???", 0)  # noSym gets highest number
        self.tab.setup_anys()
        self.tab.renumber_pragmas()

        if self.tab.ddt[2]:
            self.tab.print_nodes()

        if self.errors.count == 0:
            sys.stdout.write("checking\n")
            self.tab.comp_symbol_sets()
            if self.tab.ddt[7]:
                self.tab.XRef()
                if self.tab.grammar_ok():
                    sys.stdout.write("parser")
                    self.pgen.write_parser()

                    if self.genScanner:
                        sys.stdout.write(" + scanner")
                        self.dfa.write_scanner()
                        if self.tab.ddt[0]:
                            self.dfa.print_states()

                    sys.stdout.write(" generated\n")
                    if self.tab.ddt[8]:
                        self.pgen.write_statistics()

                if self.tab.ddt[6]:
                    self.tab.print_symbol_table()
                self.expect(18)

    def set_decl(self):
        self.expect(1)
        name = self.t.val
        c = self.tab.find_CharClass(name)
        if c is not None:
            self.sem_err("'{}' name declared twice".format(name))

        self.expect(17)
        s = self.set()
        if s.elements() == 0:
            self.sem_err("character set must not be empty")

        self.tab.new_CharClass(name, s)
        self.expect(18)

    def token_decl(self, typ: int):
        pass

    def token_expr(self) -> Graph:
        g: Graph = self.token_term()
        first: bool = True

        while self.weak_separator(33, 7, 8):
            g2: Graph = self.token_term()
            if first:
                self.tab.make_first_alt(g)
                first = False
            self.tab.make_alternative(g, g2)

        return g

    def set(self) -> CharSet:
        pass


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
