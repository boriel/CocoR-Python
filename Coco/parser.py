# -*- coding: utf-8 -*-

import sys
from typing import Optional

from .errors import Errors
from .scanner import Scanner, Token
from .trace import Trace
from .tab import Tab, Position, Node, Graph, Symbol, SymInfo
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
        s = self.sym()
        sym = self.tab.find_sym(s.name)
        if sym is not None:
            self.sem_err("'{}' name declared twice".format(s.name))
        else:
            sym = self.tab.new_sym(typ, s.name, self.t.line)
            sym.tokenKind = Symbol.fixedToken

        self.tokenString = ''
        while not self.start_of(5):
            self.syn_err(46)
            self.get()

        if self.la.kind == 17:
            self.get()
            g = self.token_expr()
            self.expect(18)
            if s.kind == self.str_:
                self.sem_err("a literal must not be declared with a structure")
            self.tab.finish(g)
            if not self.tokenString or self.tokenString == self.noString:
                self.dfa.convert_to_states(g.l, sym)
            else:  # TokenExpr is a single string
                if self.tab.literals.get(self.tokenString) is not None:
                    self.sem_err("token string declared twice")
                self.tab.literals[self.tokenString] = sym
                self.dfa.match_literal(self.tokenString, sym)
        elif self.start_of(6):
            if s.kind == self.id:
                self.genScanner = False
            else:
                self.dfa.match_literal(sym.name, sym)
        else:
            self.syn_err(47)

        if self.la.kind == 42:
            sym.semPos = self.sem_text()
            if typ != Node.pr:
                self.sem_err("semantic action not allowed here")

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
        s = self.sim_set()
        while self.la.kind in (20, 21):
            if self.la.kind == 20:
                self.get()
                s2 = self.sim_set()
                s.or_(s2)
            else:
                self.get()
                s2 = self.sim_set()
                s.subtract(s2)
        return s

    def attr_decl(self, sym: Symbol):
        if self.la.kind == 24:
            self.get()
            if self.la.kind in (25, 26):
                if self.la.kind == 25:
                    self.get()
                else:
                    self.get()
                beg = self.la.pos
                self.type_name()
                sym.retType = self.scanner.buffer.get_string(beg, self.la.pos)
                self.expect(1)
                sym.retVar = self.t.val

                if self.la.kind == 27:
                    self.get()
                elif self.la.kind == 28:
                    self.get()
                    beg = self.la.pos
                    col = self.la.col
                    while self.start_of(9):
                        self.get()
                    self.expect(27)
                    if self.t.pos > beg:
                        sym.attrPos = Position(beg, self.t.pos, col)
                else:
                    self.syn_err(48)
            elif self.start_of(10):
                beg = self.la.pos
                col = self.la.col
                if self.start_of(11):
                    self.get()
                    while self.start_of(9):
                        self.get()

                self.expect(27)
                if self.t.pos > beg:
                    sym.attrPos = Position(beg, self.t.pos, col)
            else:
                self.syn_err(49)
        elif self.la.kind == 29:
            self.get()
            if self.la.kind in (25, 26):
                if self.la.kind == 25:
                    self.get()
                else:
                    self.get()

                beg = self.la.pos
                self.type_name()
                sym.retType = self.scanner.buffer.get_string(beg, self.la.pos)
                self.expect(1)
                sym.retVar = self.t.val
                if self.la.kind == 30:
                    self.get()
                elif self.la.kind == 28:
                    self.get()
                    beg = self.la.pos
                    col = self.la.col
                    while self.start_of(12):
                        self.get()
                    self.expect(30)
                    if self.t.pos > beg:
                        sym.attrPos = Position(beg, self.t.pos, col)
                else:
                    self.syn_err(50)
            elif self.start_of(10):
                beg = self.la.pos
                col = self.la.col
                if self.start_of(13):
                    self.get()
                    while self.start_of(12):
                        self.get()
                self.expect(30)
                if self.t.pos > beg:
                    sym.attrPos = Position(beg, self.t.pos, col)
            else:
                self.syn_err(51)
        else:
            self.syn_err(52)

    def sem_text(self) -> Position:
        self.expect(42)
        beg = self.la.pos
        col = self.la.col

        while self.start_of(14):
            if self.start_of(15):
                self.get()
            elif self.la.kind == 4:
                self.get()
                self.sem_err("bad string in semantic action")
            else:
                self.get()
                self.sem_err("missing end of previous semantic action")
        self.expect(43)
        pos = Position(beg, self.t.pos, col)
        return pos

    def expression(self) -> Graph:
        g = self.term()
        first = True
        while self.weak_separator(33, 16, 17):
            g2 = self.term()
            if first:
                self.tab.make_first_alt(g)
                first = False
            self.tab.make_alternative(g, g2)
        return g

    def sim_set(self) -> CharSet:
        s = CharSet()
        if self.la.kind == 1:
            self.get()
            c = self.tab.find_CharClass(self.t.val)
            if c is None:
                self.sem_err("undefined name '{}'".format(self.t.val))
            else:
                s.or_(c.set_)

        elif self.la.kind == 3:
            self.get()
            name = self.t.val
            name = self.tab.unescape(name[1:-1])
            for c in name:
                if self.dfa.ignore_case:
                    s.set(ord(c.lower()))
                else:
                    s.set(ord(c))

        elif self.la.kind == 3:
            n1 = self.char()
            s.set(n1)
            if self.la.kind == 22:
                self.get()
                n2 = self.char()
                for i in range(n1, n2 + 1):
                    s.set(i)

        elif self.la.kind == 23:
            self.get()
            s = CharSet()
            s.fill()

        else:
            self.syn_err(53)

        return s

    def char(self) -> int:
        self.expect(5)
        name = self.t.val
        n = 0
        name = self.tab.unescape(name[1:-1])
        if len(name) == 1:
            n = name[0]
        else:
            self.sem_err("unacceptable character value")

        if self.dfa.ignore_case and 'A' <= chr(n) <= 'Z':
            n += 32  # to lowercase

        return n

    def sym(self) -> SymInfo:
        s = SymInfo()
        s.name = "???"
        s.kind = self.id

        if self.la.kind == 1:
            self.get()
            s.kind = self.id
            s.name = self.t.val

        elif self.la.kind in (3, 5):
            if self.la.kind == 3:
                self.get()
                s.name = self.t.val
            else:
                self.get()
                s.name = '"{}"'.format(self.t.val[1:-1])

            s.kind = str
            if self.dfa.ignore_case:
                s.name = s.name.lower()

            if ' ' in s.name:
                self.sem_err("literal tokens must not contain blanks")
        else:
            self.syn_err(54)
        return s

    def type_name(self):
        self.expect(1)

        while self.la.kind in (18, 24, 31):
            if self.la.kind == 18:
                self.get()
                self.expect(1)
            elif self.la.kind == 31:
                self.get()
                self.expect(32)
            else:
                self.get()
                self.type_name()

                while self.la.kind == 28:
                    self.get()
                    self.type_name()

                self.expect(27)

    def term(self) -> Graph:
        rslv: Optional[Node] = None
        g: Optional[Graph] = None

        if self.start_of(18):
            if self.la.kind == 40:
                rslv = self.tab.new_node(Node.rslv, None, self.la.line)
                rslv.pos = self.resolver()
                g = Graph(rslv)

            g2: Graph = self.factor()
            if rslv is not None:
                self.tab.make_sequence(g, g2)
            else:
                g = g2

            while self.start_of(19):
                g2 = self.factor()
                self.tab.make_sequence(g, g2)
        elif self.start_of(20):
            g = Graph(self.tab.new_node(Node.eps, None, 0))
        else:
            self.syn_err(55)

        if g is None:  # invalid start of Term
            g = Graph(self.tab.new_node(Node.eps, None, 0))

        return g

    def resolver(self) -> Position:
        self.expect(40)
        self.expect(35)

        beg = self.la.pos
        col = self.la.col

        self.condition()
        return Position(beg, self.t.pos, col)

    def factor(self) -> Graph:
        weak: bool = False
        g: Optional[Graph] = None

        if self.la.kind in (1, 3, 5, 34):
            if self.la.kind == 34:
                self.get()
                weak = True
            s = self.sym()
            sym = self.tab.find_sym(s.name)
            if sym is None and s.kind == self.str_:
                sym = self.tab.literals.get(s.name)
            undef: bool = sym is None
            if undef:
                if s.kind == self.id:
                    sym = self.tab.new_sym(Node.t, s.name, 0)  # forward nt
                elif self.genScanner:
                    sym = self.tab.new_sym(Node.t, s.name, self.t.line)
                    self.dfa.match_literal(sym.name, sym)
                else:  # undefined string in production
                    self.sem_err("undefined string '{}' in production".format(s.name))
                    sym = self.tab.eofSy  # dummy

            typ = sym.typ
            if typ != Node.t and typ != Node.nt:
                self.sem_err("this symbol kind is not allowed in production")

            if weak:
                if typ == Node.t:
                    typ = Node.wt
                else:
                    self.sem_err("only terminals may be weak")

            p: Node = self.tab.new_node(typ, sym, self.t.line)
            g = Graph(p)

            if self.la.kind in (24, 29):
                self.attribs(p)
                if s.kind != self.id:
                    self.sem_err("a literal must not have attributes")

            if undef:
                sym.attrPos = p.pos  # dummy
                sym.retVar = p.retVar  # AH - dummy
            elif (p.pos is None) != (sym.attrPos is None) or (p.retVar is None) != (sym.retVar is None):
                self.sem_err("attribute mismatch between declaration and use of this symbol")

        elif self.la.kind == 35:
            self.get()
            g = self.expression()
            self.expect(36)

        elif self.la.kind == 31:
            self.get()
            g = self.expression()
            self.expect(32)
            self.tab.make_option(g)

        elif self.la.kind == 37:
            self.get()
            g = self.expression()
            self.expect(38)
            self.tab.make_iteration(g)

        elif self.la.kind == 42:
            pos = self.sem_text()
            p = self.tab.new_node(Node.sem, None, 0)
            p.pos = pos
            g = Graph(p)

        elif self.la.kind == 23:
            self.get()
            p = self.tab.new_node(Node.any, None, self.t.line)  # p.set is set in tab.SetupAnys
            g = Graph(p)

        elif self.la.kind == 39:
            self.get()
            p = self.tab.new_node(Node.sync, None, 0)
            g = Graph(p)

        else:
            self.syn_err(56)

        if g is None:  # invalid start of Factor
            g = Graph(self.tab.new_node(Node.eps, None, 0))

        return g

    def attribs(self, n: Node):
        if self.la.kind == 24:
            self.get()
            if self.la.kind in (25, 26):
                self.get()
                beg = self.la.pos
                while self.start_of(21):
                    if self.start_of(22):
                        self.get()
                    elif self.la.kind in (31, 35):
                        self.bracketed()
                    else:
                        self.get()
                        self.sem_err("bad string in attributes")

                n.retVar = self.scanner.buffer.get_string(beg, self.la.pos)
                if self.la.kind == 27:
                    self.get()
                elif self.la.kind == 28:
                    self.get()
                    beg = self.la.pos
                    col = self.la.col
                    while self.start_of(9):
                        if self.start_of(23):
                            self.get()
                        else:
                            self.get()
                            self.sem_err("bad string in attributes")

                    self.expect(27)
                    if self.t.pos > beg:
                        n.pos = Position(beg, self.t.pos, col)
                else:
                    self.syn_err(57)
            elif self.start_of(10):
                beg = self.la.pos
                col = self.la.col
                if self.start_of(11):
                    if self.start_of(24):
                        self.get()
                    else:
                        self.get()
                        self.sem_err("bad string in attributes")

                    while self.start_of(9):
                        if self.start_of(23):
                            self.get()
                        else:
                            self.get()
                            self.sem_err("bad string in attributes")

                self.expect(27)
                if self.t.pos > beg:
                    n.pos = Position(beg, self.t.pos, col)

            else:
                self.syn_err(58)

        elif self.la.kind == 29:
            self.get()
            if self.la.kind in (25, 26):
                self.get()
                beg = self.la.pos
                while self.start_of(25):
                    if self.start_of(26):
                        self.get()
                    elif self.la.kind in (31, 35):
                        self.bracketed()
                    else:
                        self.get()
                        self.sem_err("bad string in attributes")

                n.retVar = self.scanner.buffer.get_string(beg, self.la.pos)
                if self.la.kind == 30:
                    self.get()
                elif self.la.kind == 28:
                    self.get()
                    beg = self.la.pos
                    col = self.la.col
                    while self.start_of(12):
                        if self.start_of(27):
                            self.get()
                        else:
                            self.get()
                            self.sem_err("bad string in attributes")
                    self.expect(30)
                    if self.t.pos > beg:
                        n.pos = Position(beg, self.t.pos, col)
                else:
                    self.syn_err(59)
            elif self.start_of(10):
                beg = self.la.pos
                col = self.la.col
                if self.start_of(13):
                    if self.start_of(28):
                        self.get()
                    else:
                        self.get()
                        self.sem_err("bad string in attributes")
                    while self.start_of(12):
                        if self.start_of(27):
                            self.get()
                        else:
                            self.get()
                            self.sem_err("bad string in attributes")
                self.expect(30)
                if self.t.pos > beg:
                    n.pos = Position(beg, self.t.pos, col)
            else:
                self.syn_err(60)
        else:
            self.syn_err(61)

    def condition(self):
        while self.start_of(29):
            if self.la.kind == 35:
                self.get()
                self.condition()
            else:
                self.get()
        self.expect(36)

    def token_term(self) -> Graph:
        g = self.token_factor()
        while self.start_of(7):
            g2 = self.token_factor()
            self.tab.make_sequence(g, g2)

        if self.la.kind == 41:
            self.get()
            self.expect(35)
            g2 = self.token_expr()
            self.tab.set_context_trans(g2.l)
            self.dfa.has_ctx_moves = True
            self.tab.make_sequence(g, g2)
            self.expect(36)

        return g

    def token_factor(self) -> Graph:
        g: Optional[Graph] = None

        if self.la.kind in (1, 3, 5):
            s = self.sym()
            if s.kind == self.id:
                c = self.tab.find_CharClass(s.name)
                if c is None:
                    self.sem_err("undefined name '{}'".format(s.name))
                    c = self.tab.new_CharClass(s.name, CharSet())
                p = self.tab.new_node(Node.clas, None, 0)
                p.val = c.n
                g = Graph()
                self.tokenString = self.noString
            else:  # str
                g = self.tab.str_to_graph(s.name)
                if self.tokenString is None:
                    self.tokenString = s.name
                else:
                    self.tokenString = self.noString
        elif self.la.kind == 35:
            self.get()
            g = self.token_expr()
            self.expect(36)

        elif self.la.kind == 31:
            self.get()
            g = self.token_expr()
            self.expect(32)
            self.tab.make_option(g)
            self.tokenString = self.noString

        elif self.la.kind == 37:
            self.get()
            g = self.token_expr()
            self.expect(38)
            self.tab.make_iteration(g)
            self.tokenString = self.noString

        else:
            self.syn_err(62)

        if g is None:  # invalid start of TokenFactor
            g = Graph(self.tab.new_node(Node.eps, None, 0))

        return g

    def bracketed(self):
        if self.la.kind == 35:
            self.get()
            while self.start_of(29):
                if self.la.kind in (31, 35):
                    self.bracketed()
                else:
                    self.get()
            self.expect(36)

        elif self.la.kind == 31:
            self.get()
            while self.start_of(30):
                if self.la.kind in (31, 35):
                    self.bracketed()
                else:
                    self.get()
            self.expect(32)

        else:
            self.syn_err(63)

    def parse(self):
        self.la = Token()
        self.la.val = ""
        self.get()
        self.coco()
        self.expect(0)

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
