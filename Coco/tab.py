# -*- coding: utf-8 -*-

from typing import NamedTuple, Optional, List, Union, Set

from .charset import CharSet
from .parser import Parser
from .errors import Errors
from .trace import Trace
from . import constants


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

    first: Set[int]
    follow: Set[int]
    nts: Set[int]

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


class CNode:
    """ Node of list for finding circular productions
    """

    def __init__(self, left: Symbol, right: Symbol):
        self.left = left
        self.right = right


class Tab:
    semFeclPos: Position
    ignored: CharSet
    ddt: List[bool] = [False] * 10
    gramSy: Symbol
    eofSy: Symbol
    noSym: Symbol
    allSyncSets: Set[int]
    literals: dict

    srcName: str
    srcDir: str
    nsName: str
    frameDir: str
    outDir: str
    checkEOF: bool = False

    visited: Set[int]
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

    # ---------------------------------------------------------------------
    #   Symbol set computations
    # ---------------------------------------------------------------------

    # Computes the first set for the graph rooted at p

    def first0(self, p: Node, mark: Set[int]) -> Set[int]:
        fs: Set[int] = set()
        while p is not None and p.n not in mark:
            mark.add(p.n)
            if p.typ == Node.nt:
                if p.sym.firstReady:
                    fs.update(p.sym.first)
                else:
                    fs.update(self.first0(p.sym.graph, mark))
            elif p.typ in (Node.t, Node.wt):
                fs.add(p.sym.n)
            elif p.typ == Node.any:
                fs.update(p.set_)
            elif p.typ == Node.alt:
                fs.update(self.first0(p.sub, mark))
                fs.update(self.first0(p.down, mark))
            elif p.typ in (Node.iter, Node.opt):
                fs.update(self.first0(p.sub, mark))

            if not self.del_node(p):
                break
            p = p.next

        return fs

    def first(self, p: Node) -> Set[int]:
        fs = self.first0(p, set())
        if self.ddt[3]:
            self.trace.write_line()
            if p is not None:
                self.trace.write_line("First: node = {}".format(p.n))
            else:
                self.trace.write_line("First: node = null")
                self.print_set(fs, 0)

        return fs

    def comp_first_sets(self):
        for sym in self.nonterminals:
            sym.first = set()
            sym.firstReady = False

        for sym in self.nonterminals:
            sym.first = self.first(sym.graph)
            sym.firstReady = True

    def comp_follow(self, p: Node):
        while p is not None and p.n in self.visited:
            self.visited.add(p.n)
            if p.typ == Node.nt:
                s = self.first(p.next)
                p.sym.follow.update(s)
                if self.del_graph(p.next):
                    p.sym.nts.add(self.curSy.n)
            elif p.typ == Node.opt or p.typ == Node.iter:
                self.comp_follow(p.sub)
            elif p.typ == Node.alt:
                self.comp_follow(p.sub)
                self.comp_follow(p.down)
            p = p.next

    def complete(self, sym: Symbol):
        if sym.n not in self.visited:
            self.visited.add(sym.n)
            for s in self.nonterminals:
                if s.n in sym.nts:
                    self.complete(s)
                    sym.follow.update(s.follow)
                    if sym == self.curSy:
                        sym.nts.remove(s.n)

    def comp_follow_sets(self):
        for sym in self.nonterminals:
            sym.follow = set()
            sym.nts = set()

        self.gramSy.follow.add(self.eofSy.n)
        self.visited = set()

        for sym in self.nonterminals:
            self.curSy = sym
            self.comp_follow(self.curSy.graph)

        for sym in self.nonterminals:
            self.curSy = sym
            self.visited = set()
            self.complete(self.curSy)

    def leading_any(self, p: Node) -> Optional[Node]:
        if p is None:
            return None

        a: Optional[Node] = None
        if p.typ == Node.any:
            a = p
        elif p.typ == Node.alt:
            a = self.leading_any(p.sub)
            if a is None:
                a = self.leading_any(p.down)
        elif p.typ == Node.opt or p.typ == Node.iter:
            a = self.leading_any(p.sub)
        if a is None and self.del_node(p) and not p.up:
            a = self.leading_any(p.next)

        return a

    def find_as(self, p: Node):
        """ Find ANY sets
        """
        while p is not None:
            if p.typ == Node.opt or p.typ == Node.iter:
                self.find_as(p.sub)
                a = self.leading_any(p.sub)
                if a is not None:
                    a.set_ -= self.first(p.next)

            elif p.typ == Node.alt:
                s1 = set()
                q = p
                while q is not None:
                    self.find_as(q.sub)
                    a = self.leading_any(q.sub)

                    if a is not None:
                        h = self.first(q.down)
                        h.update(s1)
                        a.set_ -= h
                    else:
                        s1.update(self.first(q.sub))

                    q = q.down

            # Remove alternative terminals before ANY, in the following
            # examples a and b must be removed from the ANY set:
            # [a] ANY, or {a|b} ANY, or [a][b] ANY, or (a|) ANY, or
            # A = [a]. A ANY
            if self.del_node(p):
                a = self.leading_any(p.next)
                if a is not None:
                    q = p.sym.graph if p.typ == Node.nt else p.sub
                    a.set_ -= self.first(q)

            if p.up:
                break

            p = p.next

    def comp_any_sets(self):
        for sym in self.nonterminals:
            self.find_as(sym.graph)

    def expected(self, p: Node, curSy: Symbol) -> Set[int]:
        s: Set[int] = self.first(p)

        if self.del_graph(p):
            s.update(curSy.follow)
        return s

    def expected0(self, p: Node, curSy: Symbol) -> Set[int]:
        if p.typ == Node.rslv:
            return set()
        return self.expected(p, curSy)

    def comp_sync(self, p: Node):
        while p is not None and p.n not in self.visited:
            self.visited.add(p.n)

            if p.typ == Node.sync:
                s = self.expected(p.next, self.curSy)
                s.add(self.eofSy.n)
                self.allSyncSets.update(s)
                p.set_ = s
            elif p.typ == Node.alt:
                self.comp_sync(p.sub)
                self.comp_sync(p.down)
            elif p.typ == Node.opt or p.typ == Node.iter:
                self.comp_sync(p.sub)

            p = p.next

    def comp_sync_sets(self):
        self.allSyncSets = {self.eofSy.n}
        self.visited = set()

        for curSy in self.nonterminals:
            self.comp_sync(curSy.graph)

    def setup_anys(self):
        for p in self.nodes:
            if p.typ == Node.any:
                p.set = {0, len(self.terminals)}
                p.set.discard(self.eofSy.n)

    def comp_deletable_symbols(self):
        changed = True
        while changed:
            changed = False
            for sym in self.nonterminals:
                if not sym.deletable and sym.graph is not None and self.del_graph(sym.graph):
                    sym.deletable = True
                    changed = True

        for sym in self.nonterminals:
            if sym.deletable:
                self.errors.warning(" {} deletable".format(sym.name))

    def renumber_pragmas(self):
        n = len(self.terminals)
        for sym in self.pragmas:
            sym.n = n
            n += 1

    def comp_symbol_sets(self):
        self.comp_deletable_symbols()
        self.comp_first_sets()
        self.comp_any_sets()
        self.comp_follow_sets()
        self.comp_sync_sets()

        if self.ddt[1]:
            self.trace.write_line()
            self.trace.write_line("First & follow symbols:")
            self.trace.write_line("----------------------")
            self.trace.write_line()

            for sym in self.nonterminals:
                self.trace.write_line(sym.name)
                self.trace.write("first:   ")
                self.print_set(sym.first, 10)
                self.trace.write("follow:  ")
                self.print_set(sym.follow, 10)
                self.trace.write_line()

        if self.ddt[4]:
            self.trace.write_line()
            self.trace.write_line("ANY and SYNC sets:")
            self.trace.write_line("-----------------")

            for p in self.nodes:
                if p.typ == Node.any or p.typ == Node.sync:
                    self.trace.write("Line: ")
                    self.trace.write_line(str(p.line), 4)
                    self.trace.write("Node: ")
                    self.trace.write(str(p.n), 4)
                    self.trace.write(" ")
                    self.trace.write(self.nTyp[p.typ], 4)
                    self.trace.write(": ")
                    self.print_set(p.set_, 11)

    # ---------------------------------------------------------------------
    #   String handling
    # ---------------------------------------------------------------------

    def hex2char(self, s: str) -> int:
        val = 0
        try:
            val = int(s, 16)
            if val > constants.COCO_WCHAR_MAX:
                raise ValueError()
        except ValueError:
            self.parser.sem_err("bad escape sequence in string or character")

        return val & constants.COCO_WCHAR_MAX

    @staticmethod
    def char2hex(ch: int) -> str:
        return "\\u%04X" % ch

    def unescape(self, s: str) -> str:
        buf = ''
        i = 0
        while i < len(s):
            c = s[i]
            if c != '\\':
                buf += c
                continue
            c = s[i + 1]
            if c in 'ux':
                if i + 6 < len(s):
                    buf += self.hex2char(s[i + 2: i + 6])
                    i += 6
                    continue
                else:
                    self.parser.sem_err("bad escape sequence in string or character")
                    break

            cc = {
                '\\': '\\',
                '\'': '\'',
                '\"': '\"',
                'r': '\r',
                'n': '\n',
                't': '\t',
                'v': '\u000b',
                '0': '\0',
                'b': '\b',
                'f': '\f',
                'a': '\u0007',
            }.get(c)

            if cc is None:
                self.parser.sem_err("bad escape sequence in string or character")
                break

            buf += cc

        return buf

    def escape(self, s: str) -> str:
        buf = ''
        for c in s:
            buf += {
                '\\': '\\\\',
                '\'': "\\'",
                '\"': "\\\"",
                '\t': "\\t",
                '\r': "\\r",
                '\n': "\\n"
            }.get(c, c if ' ' <= c <= '\u007f' else self.char2hex(ord(c)))

        return buf

    # ---------------------------------------------------------------------
    #   Grammar checks
    # ---------------------------------------------------------------------

    def grammar_ok(self):
        ok = self.nts_complete() and self.no_circular_productions() and self.all_nt_to_term()
        if ok:
            self.all_nt_reached()
            self.check_resolvers()
            self.check_LL1()

        return ok

    # --------------- check for circular productions ----------------------

    def get_singles(self, p: Node, singles: List[Symbol]):
        if p is None:
            return

        if p.typ == Node.nt:
            if p.up or self.del_graph(p.next):
                singles.append(p.sym)
        elif p.typ in (Node.alt, Node.iter, Node.opt):
            if p.up or self.del_graph(p.next):
                self.get_singles(p.sub, singles)
                if p.typ == Node.alt:
                    self.get_singles(p.down, singles)

        if not p.up and self.del_node(p):
            self.get_singles(p.next, singles)

    def no_circular_productions(self) -> bool:
        list_: List[CNode] = []
        for sym in self.nonterminals:
            singles: List[Symbol] = []
            self.get_singles(sym.graph, singles)
            list_.extend([CNode(sym, s) for s in singles])

        changed = True
        while changed:
            changed = False
            for n in list_:
                on_left_side = on_right_side = False
                for m in list_:
                    if n.left == m.right:
                        on_right_side = True
                    if n.right == m.left:
                        on_left_side = True

                if not on_left_side or not on_right_side:
                    list_.remove(n)
                    changed = True

        ok = True
        for n in list_:
            ok = False
            self.errors.sem_err(" {} --> {}".format(n.left.name, n.right.name))

        return ok

    # --------------- check for LL(1) errors ----------------------

    def LL1_error(self, cond: int, sym: Optional[Symbol]):
        s = "  LL1 warning in {}: ".format(self.curSy.name)
        if sym is not None:
            s += sym.name + " is "

        s += [
            "start of several alternatives",
            "start & successor of deletable structure",
            "an ANY node that matches no symbol",
            "contents of [...] or {...} must not be deletable"
        ][cond]
        self.errors.warning(s)

    def check_overlap(self, s1: Set[int], s2: Set[int], cond: int):
        for sym in self.terminals:
            if sym.n in s1 and sym.n in s2:
                self.LL1_error(cond, sym)

    def check_alts(self, p: Node):
        while p is not None:
            if p.typ == Node.alt:
                q = p
                s1: Set[int] = set()
                while q is not None:
                    s2 = self.expected0(q.sub, self.curSy)
                    self.check_overlap(s1, s2, 1)
                    s1.update(s2)
                    self.check_alts(q.sub)
                    q = q.down
            elif p.typ == Node.opt or p.typ == Node.iter:
                if self.del_sub_graph(p.sub):
                    self.LL1_error(4, None)
                else:
                    s1 = self.expected0(p.sub, self.curSy)
                    s2 = self.expected(p.next, self.curSy)
                    self.check_overlap(s1, s2, 2)
                self.check_alts(p.sub)
            elif p.typ == Node.any:
                if not p.set_:
                    self.LL1_error(3, None)

            if p.up:
                break

            p = p.next

    def check_LL1(self):
        for curSy in self.nonterminals:
            self.check_alts(curSy.graph)

    # ------------- check if resolvers are legal  --------------------

    def res_err(self, p: Node, msg: str):
        self.errors.warning(p.line, p.pos.col, msg)

    def check_res(self, p: Node, rslv_allowed: bool):
        while p is not None:
            if p.typ == Node.alt:
                expected: Set[int] = set()
                q: Node = p
                while q is not None:
                    expected.update(self.expected0(q.sub, self.curSy))
                    q = q.down

                so_far: Set[int] = set()
                q = p
                while q is not None:
                    if q.sub.typ == Node.rslv:
                        fs: Set[int] = self.expected(q.sub.next, self.curSy)
                        if fs.intersection(so_far):
                            self.res_err(q.sub, "Warning: Resolver will never be evaluated. " +
                                         "Place it at previous conflicting alternative.")
                        if not fs.intersection(expected):
                            self.res_err(q.sub, "Warning: Misplaced resolver: no LL(1) conflict.")
                    else:
                        so_far.update(self.expected(q.sub, self.curSy))

                    self.check_res(q.sub, True)
                    q = q.down

            elif p.typ in (Node.iter, Node.opt):
                if p.sub.typ == Node.rslv:
                    fs: Set[int] = self.first(p.sub.next)
                    fs_next: Set[int] = self.expected(p.next, self.curSy)
                    if not fs.intersection(fs_next):
                        self.res_err(p.sub, "Warning: Misplaced resolver: no LL(1) conflict.")

                self.check_res(p.sub, True)

            elif p.typ == Node.rslv:
                if not rslv_allowed:
                    self.res_err(p, "Warning: Misplaced resolver: no alternative.")

            if p.up:
                break
            p = p.next
            rslv_allowed = False

    def check_resolvers(self):
        for curSy in self.nonterminals:
            self.check_res(curSy.graph, False)

    # ------------- check if every nts has a production --------------------

    def nts_complete(self) -> bool:
        complete = True
        for sym in self.nonterminals:
            if sym.graph is None:
                complete = False
                self.errors.sem_err("  No production for {}".format(sym.name))

        return complete

    # -------------- check if every nts can be reached  -----------------

    def mark_reached_nts(self, p: Node):
        while p is not None:
            if p.typ == Node.nt and p.sym.n not in self.visited:
                self.visited.add(p.sym.n)
                self.mark_reached_nts(p.sym.graph)
            elif p.typ in (Node.alt, Node.iter, Node.opt):
                self.mark_reached_nts(p.sub)
                if p.typ == Node.alt:
                    self.mark_reached_nts(p.down)

            if p.up:
                break
            p = p.next

    def all_nt_reached(self) -> bool:
        ok = True
        visited: Set[int] = {self.gramSy.n}
        self.mark_reached_nts(self.gramSy.graph)
        for sym in self.nonterminals:
            if sym.n not in visited:
                ok = False
                self.errors.warning(" {} cannot be reached".format(sym.name))

        return ok
