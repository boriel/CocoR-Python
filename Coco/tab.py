# -*- coding: utf-8 -*-

from typing import NamedTuple, Optional, List, Union

from .charset import CharSet
from .parser import Parser
from .errors import Errors
from .trace import Trace


class Position(NamedTuple):
    beg: int
    end: int
    col: int
    line: int


class SymInfo(NamedTuple):
    name: str
    kind: int


class Symbol:
    fixedToken: int = 0
    classToken: int = 1
    litToken: int = 2
    classLitToken: int = 3

    n: int
    graph: 'Node'
    tokenKind: int
    deletable: bool
    firstReady: bool

    first: set
    follow: set
    nts: set

    attrPos: Position
    semPos: Position

    retType: str
    retVar: str

    def __init__(self, typ: int, name: str, line: int):
        self.typ = typ
        self.name = name
        self.line = line


class Node:
    t = 1
    pr = 2
    nt = 3
    clas = 4
    chr = 5
    wt = 6
    any = 7
    eps = 8
    sync = 9
    sem = 10
    alt = 11
    iter = 12
    opt = 13
    rslv = 14

    normalTrans = 0
    contextTrans = 1

    n: int
    next: 'Node'
    down: 'Node'
    sub: 'Node'
    up: bool
    sym: Symbol
    val: int

    code: int
    set_: set
    pos: Position

    state: 'State'
    retVar: str

    def __init__(self, typ: int, sym, line: int):
        self.typ = typ
        self.sym = sym
        self.line = line


class CharClass:
    n: int

    def __init__(self, name: str, s: 'CharSet'):
        self.name = name
        self.set_ = s


class Graph:
    l: Optional[Node] = None
    r: Optional[Node] = None

    def __init__(self, *args):
        assert len(args) < 3

        if len(args) == 2:
            assert all(isinstance(x, Node) for x in args)
            self.l, self.r = tuple(*args)
        elif len(args) == 3:
            assert isinstance(args[0], Node)
            self.l = self.r = args[0]


class Tab:
    semFeclPos: Position
    ignored: CharSet
    ddt: List[bool] = [False] * 10
    grafSy: Symbol
    eofSy: Symbol
    noSym: Symbol
    allSyncSets: set
    literals: dict

    srcName: str
    srcDir: str
    nsName: str
    frameDir: str
    outDir: str
    checkEOF: bool = False

    visited: set
    curSy: Symbol
    parser: Parser
    trace: Trace
    errors: Errors

    def __init__(self, parser: Parser):
        self.parser = parser
        self.trace = parser.trace
        self.errors = parser.errors
        self.eofSy = self.new_sym(Node.t, "EOF", 0)
        self.dummyNode = self.new_node(Node.eps, None, 0)
        self.literals = {}

    # ---------------------------------------------------------------------
    # Symbol list management
    # ---------------------------------------------------------------------

    terminals: List[Symbol] = []
    pragmas: List[Symbol] = []
    nonterminals: List[Symbol] = []

    tKind: List[str] = ["fixedToken", "classToken", "litToken", "classLitToken"]

    def new_sym(self, typ: int, name: str, line: int) -> Symbol:
        if len(name) == 2 and name[0] == '"':
            self.parser.sem_err("empty token not allowed")
            name = "???"

        sym = Symbol(typ, name, line)
        if typ == Node.t:
            sym.n = len(self.terminals)
            self.terminals.append(sym)
        elif typ == Node.pr:
            self.pragmas.append(sym)
        elif typ == Node.nt:
            sym.n = len(self.nonterminals)
            self.nonterminals.append(sym)
        return sym

    def find_sym(self, name: str) -> Optional[Symbol]:
        for s in self.terminals:
            if s.name == name:
                return s

        for s in self.nonterminals:
            if s.name == name:
                return s
        return None

    @staticmethod
    def num(p: Optional[Node]) -> int:
        return 0 if p is None else p.n

    def print_sym(self, sym: Symbol):
        self.trace.write(str(sym.n), 3)
        self.trace.write(' ')
        self.trace.write(self.name(sym.name), -14)
        self.trace.write(' ')
        self.trace.write(self.nTyp[sym.typ], 2)
        self.trace.write(" false " if sym.attrPos is None else " true  ")

        if sym.typ == Node.nt:
            self.trace.write(str(self.num(sym.graph)), 5)
            self.trace.write(" true  " if sym.deletable else " false ")
        else:
            self.trace.write("            ")

        self.trace.write(str(sym.line), 5)
        self.trace.write(" " + self.tKind[sym.tokenKind])

    def print_symbol_table(self):
        self.trace.write_line("Symbol Table:")
        self.trace.write_line("------------")
        self.trace.write_line()
        self.trace.write_line(" nr name           typ  hasAt graph  del   line tokenKind")

        for sym in self.terminals:
            self.print_sym(sym)

        for sym in self.pragmas:
            self.print_sym(sym)

        for sym in self.nonterminals:
            self.print_sym(sym)

        self.trace.write_line()
        self.trace.write_line("Literal Tokens:")
        self.trace.write_line("--------------")

        for key, value in self.literals:
            self.trace.write_line('_{} = {}.'.format(value.name, key))

        self.trace.write_line()

    def print_set(self, s: set, indent: int):
        col = indent
        for sym in self.terminals:
            if sym not in s:
                continue
            len_ = len(sym.name)
            if col + len_ >= 80:
                self.trace.write_line()
                self.trace.write(' ' * (indent - col))
                col = indent
            self.trace.write(sym.name + ' ')
            col += len_ + 1

        if col == indent:
            self.trace.write('-- empty set --')

        self.trace.write_line()

    # ---------------------------------------------------------------------
    #  Syntax graph management
    # ---------------------------------------------------------------------

    nodes: List[Node] = []
    nTyp: List[str] = ["    ", "t   ", "pr  ", "nt  ", "clas", "chr ", "wt  ", "any ", "eps ",
                       "sync", "sem ", "alt ", "iter", "opt ", "rslv"]

    def new_node(self, typ: int, sym: Union[Symbol, Node, int, None], line: int = 0) -> Node:
        if isinstance(sym, Symbol):
            node = Node(typ, sym, line)
            node.n = len(self.nodes)
            self.nodes.append(node)
            return node

        if isinstance(sym, Node):
            node = self.new_node(typ, None, line)
            node.sub = sym
            return node

        assert isinstance(sym, int)
        node = self.new_node(typ, None, line)
        node.val = sym
        return node

    def make_first_alt(self, g: Graph):
        g.l = self.new_node(Node.alt, g.l)
        g.l.line = g.l.sub.line
        g.r.up = True
        g.l.next = g.r
        g.r = g.l

    def make_alternative(self, g1: Graph, g2: Graph):
        """ The result will be in g1
        """
        g2.l = self.new_node(Node.alt, g2.l)
        g2.l.line = g2.l.sub.line
        g2.l.up = True
        g2.r.up = True

        p = g1.l
        while p.down is not None:
            p = p.down
        p.down = g2.l

        p = g1.r
        while p.next is not None:
            p = p.next

        # append alternative to g1 end list
        p.next = g2.l

        # append g2 end list to g1 end list
        g2.l.next = g2.r

    @staticmethod
    def make_sequence(g1: Graph, g2: Graph):
        """ The result will be in g1
        """
        p = g1.r.next
        g1.r.next = g2.l  # link head node
        while p is not None:  # link substructure
            q = p.next
            p.next = g2.l
            p = q
        g1.r = g2.r

    def make_iteration(self, g: Graph):
        g.l = self.new_node(Node.iter, g.l)
        g.r.up = True
        p: Node = g.r
        g.r = g.l

        while p is not None:
            q: Node = p.next
            p.next = g.l
            p = q

    def make_option(self, g: Graph):
        g.l = self.new_node(Node.opt, g.l)
        g.r.up = True
        g.l.next = g.r
        g.r = g.l

    @staticmethod
    def finish(g: Graph):
        p = g.r
        while p is not None:
            q = p.next
            p.next = None
            p = q

    def delete_nodes(self):
        self.nodes = []
        self.dummyNode = self.new_node(Node.eps, None, 0)

    def str_to_graph(self, str_: str) -> Graph:
        s = self.unescape(str_[1: -1])
        if not s:
            self.parser.sem_err("empty token not allowed")

        g = Graph()
        g.r = self.dummyNode
        for c in s:
            p = self.new_node(Node.chr, ord(c), 0)
            g.r.next = p
            g.r = p

        g.l = self.dummyNode.next
        self.dummyNode.next = None
        return g

    def set_context_trans(self, p: Node):
        while p is not None:
            if p.typ == Node.chr or p.typ == Node.clas:
                p.code = Node.contextTrans
            elif p.typ == Node.opt or p.typ == Node.iter:
                self.set_context_trans(p.sub)
            elif p.typ == Node.alt:
                self.set_context_trans(p.sub)
                self.set_context_trans(p.down)

            if p.up:
                break
            p = p.next

    # ---------------- graph deletability check ---------------------

    def del_graph(self, p: Node) -> bool:
        return p is None or self.del_node(p) and self.del_graph(p.next)

    def del_sub_graph(self, p: Node) -> bool:
        return p is None or self.del_node(p) and (p.up or self.del_sub_graph(p.next))

    def del_node(self, p: Node) -> bool:
        if p.typ == Node.nt:
            return p.sym.deletable

        if p.typ == Node.alt:
            return self.del_sub_graph(p.sub) or p.down is not None and self.del_sub_graph(p.down)

        return p.typ in (Node.iter, Node.opt, Node.sem, Node.eps, Node.sync, Node.rslv)

    # -------------------- graph printing ------------------------

    @staticmethod
    def ptr(p: Node, up: bool):
        ptr_ = "0" if p is None else str(p.n)
        return "-" + ptr_ if up else ptr_

    def pos(self, pos: Position):
        if pos is None:
            return "     "
        return self.trace.format_string(str(pos.beg), 5)

    @staticmethod
    def name(name_: str):
        return name_.rjust(12)

    def print_nodes(self):
        self.trace.write_line("Graph nodes:")
        self.trace.write_line("----------------------------------------------------")
        self.trace.write_line("   n type name          next  down   sub   pos  line")
        self.trace.write_line("                               val  code")
        self.trace.write_line("----------------------------------------------------")

        for p in self.nodes:
            self.trace.write(str(p.n), 4)
            self.trace.write(" " + self.nTyp[p.typ] + " ")
            if p.sym is not None:
                self.trace.write(self.name(p.sym.name), 12)
                self.trace.write(" ")
            elif p.typ == Node.clas:
                c = self.classes[p.val]
                self.trace.write(self.name(c.name), 12)
                self.trace.write(" ")
            else:
                self.trace.write("             ")
                self.trace.write(self.ptr(p.next, p.up), 5)
                self.trace.write(" ")

            if p.typ in (Node.t, Node.nt, Node.wt):
                self.trace.write("             ")
                self.trace.write(self.pos(p.pos), 5)
            elif p.typ == Node.chr:
                self.trace.write(str(p.val), 5)
                self.trace.write(" ")
                self.trace.write(str(p.code), 5)
                self.trace.write("       ")
            elif p.typ == Node.clas:
                self.trace.write("      ")
                self.trace.write(str(p.code), 5)
                self.trace.write("       ")
            elif p.typ in (Node.alt, Node.iter, Node.opt):
                self.trace.write(self.ptr(p.down, False), 5)
                self.trace.write(" ")
                self.trace.write(self.ptr(p.sub, False), 5)
                self.trace.write("       ")
            elif p.typ == Node.sem:
                self.trace.write("             ")
                self.trace.write(self.pos(p.pos), 5)
            elif p.typ in (Node.eps, Node.any, Node.sync):
                self.trace.write("                  ")

            self.trace.write_line(str(p.line), 5)
        self.trace.write_line()

    # ---------------------------------------------------------------------
    #   character class management
    # ---------------------------------------------------------------------

    classes: List[CharClass] = []
    dummyName: int = ord('A')

    def new_CharClass(self, name: str, s: CharSet) -> CharClass:
        if name == "#":
            name = "#" + chr(self.dummyName)
            self.dummyName += 1

        c = CharClass(name, s)
        c.n = len(self.classes)
        self.classes.append(c)
        return c

    def find_CharClass(self, s: Union[str, CharSet]) -> Optional[CharClass]:
        if isinstance(s, str):  # by name
            for c in self.classes:
                if c.name == s:
                    return c
            return None

        # s is a CharSet
        for c in self.classes:
            if s.equals(c.set_):
                return c
        return None

    def CharClass_set(self, i: int) -> CharSet:
        return self.classes[i].set_

    # -------------------- character class printing -----------------------

    @staticmethod
    def ch(ch_: int) -> str:
        ch_ = chr(ch_)
        if ch_ < ' ' or ch_ > chr(127) or ch_ == '\'' or ch_ == '\\':
            return ch_
        return "'{}'".format(ch_)

    def write_char_set(self, s: CharSet):
        for r in s.ranges:
            if r.from_ < r.to:
                self.trace.write("{}..{} ".format(self.ch(r.from_), self.ch(r.to)))
            else:
                self.trace.write(self.ch(r.from_) + " ")

    def write_CharClasses(self):
        for c in self.classes:
            self.trace.write(c.name + ": ", -10)
            self.write_char_set(c.set_)
            self.trace.write_line()
        self.trace.write_line()
