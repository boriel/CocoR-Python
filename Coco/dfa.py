# -*- coding: utf-8 -*-

from typing import List, BinaryIO, TextIO, Optional, Set, Any, Generator

from .tab import Node, Symbol, Tab
from .charset import CharSet
from .parser import Parser
from .errors import Errors
from .trace import Trace


class Target:
    state: 'State'
    next: Optional['State']

    def __init__(self, state: 'State'):
        self.state = state
        self.next = None


class Comment:
    next: 'Comment'

    def __init__(self, start: str, stop: str, nested: bool):
        self.start = start
        self.stop = stop
        self.nested = nested


class Action:
    typ: int
    sym: int
    tc: int
    target: Optional[Target]

    def __init__(self, typ: int, sym: int, tc: int):
        self.typ = typ
        self.sym = sym
        self.tc = tc
        self.target = None

    def add_target(self, t: Target):
        last = None
        p = self.target

        while p is not None and t.state.nr >= p.state.nr:
            if t.state == p.state:
                return
            last, p = p, p.next

        t.next = p
        if p == self.target:
            self.target = t
        else:
            last.next = t

    def add_targets(self, a: 'Action'):
        p = a.target
        while p is not None:
            self.add_target(Target(p.state))
            p = p.next

        if a.tc == Node.contextTrans:
            self.tc = Node.contextTrans

    def symbols(self, tab: Tab) -> CharSet:
        if self.typ == Node.clas:
            s = tab.CharClass_set(self.sym).clone()
        else:
            s = CharSet()
            s.set(self.sym)
        return s

    def shift_with(self, s: CharSet, tab: Tab):
        if s.elements() == 1:
            self.typ = Node.chr
            self.sym = s.first()
        else:
            c = tab.find_CharClass(s)
            if c is None:
                c = tab.new_CharClass('#', s)
                self.typ = Node.clas
                self.sym = c.n


class State:
    nr: int  # State number
    actions: List[Action]
    endOf: Symbol
    ctx: bool
    next: 'State'

    def __init__(self):
        self.ctx = False
        self.actions = []

    def add_action(self, act: Action):
        i = 0
        for i, action in enumerate(self.actions):
            if act.typ < action.typ:
                break
        self.actions.insert(i, act)

    def detach_action(self, act: Action):
        try:
            i = self.actions.index(act)
            self.actions.pop(i)
        except ValueError:
            pass

    def melt_with(self, s: 'State'):
        for action in s.actions:
            a = Action(action.typ, action.sym, action.tc)
            a.add_targets(action)
            self.add_action(a)

    @property
    def first_action(self) -> Action:
        return None if not self.actions else self.actions[0]


class Melted:
    def __init__(self, set_: set, state: State):
        self.set_ = set_
        self.state = state


class DFA:
    ignore_case: bool       # true if input should be treated case-insensitively
    has_ctx_moves: bool     # DFA has context transitions

    max_states: int
    last_state_nr: int      # highest state number
    _first_state: State
    _last_state: State      # last allocated state
    last_sim_state: int     # last non melted state
    fram: BinaryIO          # scanner frame input     /* pdt */
    gen: TextIO             # generated scanner file  /* pdt */
    curSy: Symbol           # current token to be recognized (in FindTrans)
    dirty_DFA: bool         # DFA may become nondeterministic in MatchLiteral

    tab: Tab                # other Coco objects
    parser: Parser
    errors: Errors
    trace: Trace

    # ---------- Output primitives
    @staticmethod
    def ch(ch: int) -> str:
        return str(ch)  # in Python "chars" are always integers

    @staticmethod
    def ch_cond(ch: int) -> str:
        return "ch == {}".format(ch)

    def put_range(self, s: CharSet):
        for i, r in enumerate(s.ranges):
            if r.from_ == r.to:
                self.gen.write("ch == {}".format(self.ch(r.from_)))
            elif r.from_ == 0:
                self.gen.write("ch <= {}".format(self.ch(r.to)))
            else:
                self.gen.write("ch >= {} and ch <= {}".format(r.from_, r.to))

            if i != len(s.ranges) - 1:
                self.gen.write(" || ")

    # ---------- State handling

    def new_state(self) -> State:
        s = State()
        self.last_state_nr += 1
        s.nr = self.last_state_nr
        if self._first_state is None:
            self._first_state = s
        else:
            self._last_state.next = s

        self._last_state = s
        return s

    def new_transition(self, from_: State, to: State, typ: int, sym: int, tc: int):
        t = Target(to)
        a = Action(typ=typ, sym=sym, tc=tc)
        a.target = t
        from_.add_action(a)

        if typ == Node.clas:
            self.curSy.tokenKind = Symbol.classToken

    def combine_shifts(self):
        state: State = self._first_state

        while state is not None:
            to_detach = []
            for i, a in enumerate(state.actions):
                for b in state.actions[i + 1:]:
                    if a.target[0].state == b.target[0].state and a.tc == b.tc:
                        seta = a.symbols(self.tab)
                        setb = b.symbols(self.tab)
                        seta.or_(setb)
                        a.shift_with(seta, self.tab)
                        to_detach.append(b)

            for action in to_detach:
                state.detach_action(action)

            state = state.next

    def find_used_states(self, state: State, used: Set[int]):
        if state.nr in used:
            return
        used.add(state.nr)
        for a in state.actions:
            self.find_used_states(a.target.state, used)

    def delete_redundant_states(self):
        new_state = [None] * self.last_state_nr + 1
        used = set()
        self.find_used_states(self._first_state, used)

        # combine equal final states
        s1 = self._first_state.next
        while s1 is not None:
            if s1.nr in used and s1.endOf is not None and s1.first_action is None and not s1.ctx:
                s2 = s1.next

                while s2 is not None:
                    if s2.nr in used and s1.endOf == s2.endOf and s2.first_action is None and not s2.ctx:
                        used.discard(s2.nr)
                        new_state[s2.nr] = s1
                    s2 = s2.next

            s1 = s1.next

        for state in self.states():
            if state.nr in used:
                for a in state.actions:
                    if a.target.state.nr not in used:
                        a.target.state = new_state[a.target.state.nr]

        # delete unused states
        self._last_state = self._first_state
        self.last_state_nr = 0  # firstState has number 0

        for state in self.states():
            if state.nr in used:
                self.last_state_nr += 1
                state.nr = self.last_state_nr
                self._last_state = state
            else:
                self._last_state.next = state.next

    def the_state(self, p: Node) -> State:
        if p is None:
            state = self.new_state()
            state.endOf = self.curSy
            return state

        return p.state

    def step(self, from_:State, p: Node, stepped: Set[int]):
        if p is None:
            return

        stepped.add(p.n)
        if p.typ in (Node.clas, Node.chr):
            self.new_transition(from_, self.the_state(p.next), p.typ, p.val, p.code)
        elif p.typ == Node.alt:
            self.step(from_, p.sub, stepped)
            self.step(from_, p.down, stepped)
        elif p.typ == Node.iter:
            if self.tab.del_sub_graph(p.sub):
                self.parser.sem_err("contents of {...} must not be deletable")
                return
            if p.next is not None and p.next.n not in stepped:
                self.step(from_, p.next, stepped)
            self.step(from_, p.sub, stepped)
            if p.state != from_:
                self.step(p.state, p, set())
        elif p.typ == Node.opt:
            if p.next is not None and p.next.n not in stepped:
                self.step(from_, p.next, stepped)
            self.step(from_, p.sub, stepped)

    # Assigns a state n.state to every node n. There will be a transition from
    # n.state to n.next.state triggered by n.val. All nodes in an alternative
    # chain are represented by the same state.
    # Numbering scheme:
    #  - any node after a chr, clas, opt, or alt, must get a new number
    #  - if a nested structure starts with an iteration the iter node must get a new number
    #  - if an iteration follows an iteration, it must get a new number
    def number_nodes(self, p: Node, state: Optional[State], renum_iter: bool):
        if p is None:
            return
        if p.state is not None:  # already visited
            return
        if state is None or p.typ == Node.iter and renum_iter:
            state = self.new_state()
        p.state = state

        if self.tab.del_graph(p):
            state.endOf = self.curSy

        if p.typ in (Node.clas, Node.chr):
            self.number_nodes(p.next, None, False)
        elif p.typ == Node.opt:
            self.number_nodes(p.next, None, False)
            self.number_nodes(p.sub, state, True)
        elif p.typ == Node.iter:
            self.number_nodes(p.next, state, True)
            self.number_nodes(p.sub, state, True)
        elif p.typ == Node.alt:
            self.number_nodes(p.next, None, False)
            self.number_nodes(p.sub, state, True)
            self.number_nodes(p.down, state, renum_iter)

    def find_trans(self, p: Node, start: bool, marked: Set[int]):
        if p is None or p.n in marked:
            return
        marked.add(p.n)

        if start:
            self.step(p.state, p, set())

        if p.typ in (Node.clas, Node.chr):
            self.find_trans(p.next, True, marked)
        elif p.typ == Node.opt:
            self.find_trans(p.next, True, marked)
            self.find_trans(p.sub, False, marked)
        elif p.typ == Node.iter:
            self.find_trans(p.next, False, marked)
            self.find_trans(p.sub, False, marked)
        elif p.typ == Node.alt:
            self.find_trans(p.sub, False, marked)
            self.find_trans(p.down, False, marked)

    def convert_to_states(self, p: Node, sym: Symbol):
        self.curSy = sym
        if self.tab.del_graph(p):
            self.parser.sem_err("token might be empty")
            return

        self.number_nodes(p, self._first_state, True)
        self.find_trans(p, True, set())
        if p.typ == Node.iter:
            self.step(self._first_state, p, set())

    def match_literal(self, s: str, sym: Symbol):
        """ Match string against current automaton;
        store it either as a fixedToken or as a litToken
        """
        s = self.tab.unescape(s[1:-1])
        len_ = len(s)
        state = self._first_state
        a = None
        i = 0
        while i < len_:  # try to match s against existing DFA
            a = self.find_action(state, ord(s[i]))
            if a is None:
                break
            state = a.target.state
            i += 1

        # if s was not totally consumed or leads to a non-final state => make new DFA from it
        if i != len_ or state.endOf is None:
            state = self._first_state
            i = 0
            a = None
            self.dirty_DFA = True

        for i in range(i, len_):  # make new DFA for s[i..len-1]
            to = self.new_state()
            self.new_transition(state, to, Node.chr, ord(s[i]), Node.normalTrans)
            state = to

        matched_sym = state.endOf
        if state.endOf is None:
            state.endOf = sym
        elif matched_sym.tokenKind == Symbol.fixedToken or a is not None and a.tc == Node.contextTrans:
            # matched a token with a fixed definition or a token with an appendix that will be cut off
            self.parser.sem_err("tokens {} and {} cannot be distinguished".format(sym.name, matched_sym.name))
        else:  # matchedSym == classToken || classLitToken
            matched_sym.tokenKind = Symbol.classLitToken
            sym.tokenKind = Symbol.litToken

    def states(self) -> Generator[State]:
        state = self._first_state
        while state is not None:
            yield state
            state = state.next

    def split_actions(self, state: State, a: Action, b: Action):
        seta = a.symbols(self.tab)
        setb = b.symbols(self.tab)
        if seta.equals(setb):
            a.add_targets(b)
            state.detach_action(b)
        elif seta.includes(setb):
            setc = seta.clone()
            setc.subtract(setb)
            b.add_targets(a)
            a.shift_with(setc, self.tab)
        elif setb.includes(seta):
            setc = setb.clone()
            setc.subtract(seta)
            a.add_targets(b)
            b.shift_with(setc, self.tab)
        else:
            setc = seta.clone()
            setc.and_(setb)
            seta.subtract(setc)
            setb.subtract(setc)
            a.shift_with(seta, self.tab)
            b.shift_with(setb, self.tab)
            c = Action(0, 0, Node.normalTrans)  # typ and sym are set in ShiftWith
            c.add_targets(a)
            c.add_targets(b)
            c.shift_with(setc, self.tab)
            state.add_action(c)

    def overlap(self, a: Action, b: Action) -> bool:
        if a.typ == Node.chr:
            if b.typ == Node.chr:
                return a.sym == b.sym
            setb = self.tab.CharClass_set(b.sym)
            return setb.get(a.sym)
        seta = self.tab.CharClass_set(a.sym)
        if b.typ == Node.chr:
            return seta.get(b.sym)
        setb = self.tab.CharClass_set(b.sym)
        return seta.intersects(setb)

    def make_unique(self, state: State):
        changed = True
        while changed:
            changed = False
            for i, a in enumerate(state.actions):
                for b in state.actions[i + 1:]:
                    if self.overlap(a, b):
                        self.split_actions(a, b)
                        changed = True

    def melt_states(self, state: State):
        for action in state.actions:
            if action.target.next is None:
                param: List[Any] = [None] * 2
                ctx = self.get_target_states(action, param)
                targets: Optional[Set[int]] = param[0]
                end_of: Optional[Symbol] = param[1]

                melt: Optional[Melted] = self.state_with_set(targets)
                if melt is None:
                    s = self.new_state()
                    s.endOf = end_of
                    s.ctx = ctx

                    targ = action.target
                    while targ is not None:
                        s.melt_with(targ.state)
                        targ = targ.next

                    self.make_unique(s)
                    melt = self.new_melted(targets, s)

                action.target.next = None
                action.target.state = melt.state

    def find_ctx_states(self):
        for state in self.states():
            for a in state.actions:
                if a.tc == Node.contextTrans:
                    a.target.state.ctx = True

    def make_deterministic(self):
        last_sim_state = self._last_state.nr
        max_states = 2 * last_sim_state  # heuristic for set size in Melted.set
        self.find_ctx_states()

        for state in self.states():
            self.make_unique(state)

        for state in self.states():
            self.melt_states(state)

        self.delete_redundant_states()
        self.combine_shifts()

    def print_states(self):
        self.trace.write_line()
        self.trace.write_line("---------- states ----------")

        for state in self.states():
            first = True
            if state.endOf is None:
                self.trace.write("               ")
            else:
                self.trace.write("E({})".format(state.endOf.name), 12)
            self.trace.write("{}:".format(state.nr), 3)
            if state.first_action is None:
                self.trace.write_line()

            for action in state.actions:
                if first:
                    first = False
                    self.trace.write(" ")
                else:
                    self.trace.write("                   ")

                if action.typ == Node.clas:
                    self.trace.write(self.tab.classes[action.sym].name)
                else:
                    self.trace.write(self.ch(action.sym), 3)

                targ = action.target
                while targ is not None:
                    self.trace.write(str(targ.state.nr), 3)
                    targ = targ.next

                if action.tc == Node.contextTrans:
                    self.trace.write_line(" context")
                else:
                    self.trace.write_line()

        self.trace.write_line()
        self.trace.write_line("---------- character classes ----------")
        self.tab.write_CharClasses()

    # ------------------------ actions ------------------------------
    def find_action(self, state: State, ch: int) -> Optional[Action]:
        for a in state.actions:
            if a.typ == Node.chr and ch == a.sym:
                return a
            if a.typ == Node.clas:
                s = self.tab.CharClass_set(a.sym)
                if s.get(ch):
                    return a

        return None
