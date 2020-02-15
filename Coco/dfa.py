# -*- coding: utf-8 -*-

from typing import List, BinaryIO, TextIO, Optional, Set, Any, Generator

from .tab import Node, Symbol, Tab
from .charset import CharSet
from .parser import Parser
from .errors import Errors, FatalError
from .trace import Trace
from .generator import Generator as Generator_


class Target:
    state: 'State'
    next: Optional['State']

    def __init__(self, state: 'State'):
        self.state = state
        self.next = None


class Comment:
    next: Optional['Comment']

    def __init__(self, start: str, stop: str, nested: bool):
        self.start = start
        self.stop = stop
        self.nested = nested
        self.next = None


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

    def targets_iterator(self) -> Generator[Target]:
        target = self.target
        while target is not None:
            yield target
            target = target.next


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
    _first_state: Optional[State]
    _last_state: Optional[State]   # last allocated state
    last_sim_state: int     # last non melted state
    fram: BinaryIO          # scanner frame input     /* pdt */
    gen: TextIO             # generated scanner file  /* pdt */
    curSy: Symbol           # current token to be recognized (in FindTrans)
    dirty_DFA: bool         # DFA may become nondeterministic in MatchLiteral

    tab: Tab                # other Coco objects
    parser: Parser
    errors: Errors
    trace: Trace

    def DFA(self, parser: Parser):
        self.parser = parser
        self.tab = parser.tab
        self.errors = parser.errors
        self.trace = parser.trace
        self._first_state = None
        self._last_state = None
        self.last_state_nr = -1
        self._first_state = self.new_state()
        self.first_melted = None
        self.first_comment = None
        self.ignore_case = False
        self.dirty_DFA = False
        self.has_ctx_moves = False

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
        new_state: List[Optional[State]] = [None] * (self.last_state_nr + 1)
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
                        self.split_actions(state, a, b)
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

                    for targ in action.targets_iterator():
                        s.melt_with(targ.state)

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

                for targ in action.targets_iterator():
                    self.trace.write(str(targ.state.nr), 3)

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

    def get_target_states(self, a: Action, param: List[Any]) -> bool:
        """ Compute the set of target states
        """
        ctx = False
        targets: Set[int] = set()
        end_of: Optional[Symbol] = None

        for t in a.targets_iterator():
            state_nr = t.state.nr
            if state_nr < self.last_sim_state:
                targets.add(state_nr)
            else:
                targets.update(self.melted_set(state_nr))

            if t.state.endOf is not None:
                if end_of is None or end_of == t.state.endOf:
                    end_of = t.state.endOf
                else:
                    self.errors.sem_err("Tokens {} and {} "
                                        "cannot be distinguished".format(end_of.name, t.state.endOf.name))
            if t.state.ctx:
                ctx = True

        param[0] = targets
        param[1] = end_of
        return ctx

    # ---------------------- melted states --------------------------

    first_melted: Optional[Melted] = None  # head of melted state list

    def melted_iterator(self) -> Generator[Melted]:
        m = self.first_melted
        while m is not None:
            yield m
            m = m.next

    def new_melted(self, set_: Set[int], state: State) -> Melted:
        m = Melted(set_, state)
        m.next = self.first_melted
        self.first_melted = m
        return m

    def melted_set(self, nr: int) -> Set[int]:
        for m in self.melted_iterator():
            if m.state.nr == nr:
                return m.set_

        raise FatalError("Compiler error in Melted.Set")

    def state_with_set(self, s: Set[int]) -> Optional[Melted]:
        for m in self.melted_iterator():
            if s == m.set_:
                return m

        return None

    # ------------------------- comments ----------------------------
    first_comment: Optional[Comment] = None

    def comment_str(self, p: Node) -> str:
        s = ''
        while p is not None:
            if p.typ == Node.chr:
                s += chr(p.val)
            elif p.typ == Node.clas:
                set_ = self.tab.CharClass_set(p.val)
                if set_.elements() != 1:
                    self.parser.sem_err("character set contains more than 1 character")
                s += chr(set_.first())
            else:
                self.parser.sem_err("comment delimiters must be 1 or 2 characters long")
                s = "?"

        return s

    def new_comment(self, from_:Node, to: Node, nested: bool):
        c = Comment(self.comment_str(from_), self.comment_str(to), nested)
        c.next = self.first_comment
        self.first_comment = c

    # --------------------- scanner generation ------------------------
    def print(self, s: str = ''):
        self.gen.write(s.replace('\t', ' ' * 4))

    def println(self, s: str = ''):
        self.print(s + '\n')

    def gen_com_body(self, com: Comment):
        self.println("\t\t\twhile True:")
        self.println('\t\t\t\tif {}:'.format(self.ch_cond(ord(com.stop[0]))))

        if len(com.stop) == 1:
            self.println('\t\t\t\t\tlevel -= 1')
            self.println('\t\t\t\t\tif level == 0:')
            self.println('\t\t\t\t\t\tself.old_eols = self.line - line0')
            self.println('\t\t\t\t\t\tself.next_ch()')
            self.println('\t\t\t\t\t\treturn True')
            self.println('\t\t\t\t\tself.next_ch()')
        else:
            self.println('\t\t\t\t\tself.next_ch()')
            self.println('\t\t\t\t\tif {}:'.format(self.ch_cond(ord(com.stop[1]))))
            self.println('\t\t\t\t\t\tlevel -= 1')
            self.println('\t\t\t\t\t\tif level == 0:')
            self.println('\t\t\t\t\t\t\tself.old_eols = self.line - line0')
            self.println('\t\t\t\t\t\t\tself.next_ch()')
            self.println('\t\t\t\t\t\t\treturn True')
            self.println('\t\t\t\t\t\tself.next_ch()')

        if com.nested:
            self.println('\t\t\t\telif {}:'.format(self.ch_cond(ord(com.start[0]))))
            if len(com.start) == 1:
                self.println('\t\t\t\t\tlevel += 1')
                self.println('\t\t\t\t\tself.next_ch()')
            else:
                self.println('\t\t\t\t\tself.next_ch()')
                self.println('\t\t\t\t\tif {}:'.format(self.ch_cond(ord(com.start[1]))))
                self.println('\t\t\t\t\t\tlevel += 1')
                self.println('\t\t\t\t\t\tself.next_ch()')

        self.println('\t\t\t\telif self.ch == Buffer.EOF:')
        self.println('\t\t\t\t\treturn False')
        self.println('\t\t\t\telse:')
        self.println('\t\t\t\t\tself.next_ch()')

    def gen_comment(self, com: Comment, i: int):
        self.println()
        self.println('\tdef comment{}(self) -> bool:'.format(i))
        self.println('\t\tlevel:int = 1')
        self.println('\t\tpos0 = self.pos')
        self.println('\t\tline0 = self.line')
        self.println('\t\tcol0 = self.col')
        self.println('\t\tchar_pos0 = self.char_pos')

        if len(com.start) == 1:
            self.println('\t\tself.next_ch()')
            self.gen_com_body(com)
        else:
            self.println('\t\tself.next_ch()')
            self.println('\t\tif {}:'.format(self.ch_cond(ord(com.start[1]))))
            self.println('\t\t\tself.next_ch()')
            self.gen_com_body(com)
            self.println('\t\telse:')
            self.println('\t\t\tself.set_pos(pos0)')
            self.println('\t\t\tself.next_ch()')
            self.println('\t\t\tself.line = line0')
            self.println('\t\t\tself.col = col0')
            self.println('\t\t\tself.char_pos = char_pos0')
            self.println('\t\treturn False')

        self.println()

    def sym_name(self, sym: Symbol):
        if sym.name[0].isalpha():  # real name value is stored in Tab.literals
            for me_key, me_val in self.tab.literals.items():
                if me_val == sym:
                    return me_key

        return sym.name

    def gen_literals(self):
        ts = [self.tab.terminals, self.tab.pragmas]
        for iter_ in ts:
            for sym in iter_:
                if sym.tokenKind == Symbol.litToken:
                    name = self.sym_name(sym)
                    if self.ignore_case:
                        name = name.lower()
                    self.println('\t\tself.literals[{}] = {}'.format(name, sym.n))

    def write_state(self, state: State):
        endOf: Symbol = state.endOf
        self.println('\t\t\t\tif state == {}:'.format(state.nr, 1))
        if endOf is not None and state.first_action is not None:
            self.println('\t\t\t\t\trec_end = pos')
            self.println('\t\t\t\t\trec_kind = {}'.format(endOf.n))

        ctx_end: bool = state.ctx
        for action in state.actions:
            if action == state.first_action:
                self.print('\t\t\t\t\tif ')
            else:
                self.print('\t\t\t\t\telif ')

            if action.typ == Node.chr:
                self.print(self.ch_cond(action.sym))
            else:
                self.put_range(self.tab.CharClass_set(action.sym))

            self.println(':')
            if action.tc == Node.contextTrans:
                self.println('\t\t\t\t\t\tapx += 1')
                ctx_end = False
            elif state.ctx:
                self.println('\t\t\t\t\t\tapx = 0')

            self.println('\t\t\t\t\t\tself.add_ch()')
            self.println('\t\t\t\t\t\tstate = {}'.format(action.target.state.nr))

        if state.first_action is None:
            self.println('\t\t\t\t\t:')
        else:
            self.println('\t\t\t\t\telse:')

        if ctx_end:  # final context state: cut appendix
            self.println('\t\t\t\t\t\tself.set_scanner_behind_T()')

        if endOf is None:
            self.println('\t\t\t\t\t\tstate = 0')
        else:
            self.println('\t\t\t\t\t\tself.t.kind = {}'.format(endOf.n))
            if endOf.tokenKind == Symbol.classLitToken:
                self.println('\t\t\t\t\t\tself.t.val = self.tval')
                self.println('\t\t\t\t\t\tself.check_literal()')
                self.println('\t\t\t\t\t\treturn self.t')
            else:
                self.println('\t\t\t\t\t\tbreak')

    def write_start_tab(self):
        for action in self._first_state.actions:
            target_state = action.target.state.nr
            if action.typ == Node.chr:
                self.println('\t\tself.start[{}] = {}'.format(action.sym, target_state))
            else:
                s: CharSet = self.tab.CharClass_set(action.sym)
                for r in s.ranges:
                    self.println('\t\tfor i in range({}, {}):'.format(r.from_, r.to + 1))
                    self.println('\t\t\tself.start[i] = {}'.format(target_state))

        self.println('\t\tself.start[Buffer.EOF] = -1')

    def write_scanner(self):
        g: Generator_ = Generator_(self.tab)
        self.fram = g.open_file("Scanner.frame")
        self.gen = g.open_gen("Scanner.java")
        if self.dirty_DFA:
            self.make_deterministic()

        g.gen_copyright()
        g.skip_frame_part('-->begin')

        g.copy_frame_part('-->declarations')
        self.println('\tmaxT: int = {}'.format(len(self.tab.terminals) - 1))
        self.println('\tnoSym: int = {}'.format(self.tab.noSym.n))

        if self.ignore_case:
            self.print('\tvalCh: str  # Current input character (for token.val)')

        g.copy_frame_part('-->initialization')
        self.write_start_tab()
        self.gen_literals()

        g.copy_frame_part('-->casing')
        if self.ignore_case:
            self.println('\t\tif self.ch != Buffer.EOF')
            self.println('\t\t\tself.valCh = chr(self.ch)')
            self.println('\t\t\tself.ch = ord(self.valCh.lower())')

        g.copy_frame_part('-->casing2')
        if self.ignore_case:
            self.println('\t\t\tself.tval += self.valCh')
        else:
            self.println('\t\t\tself.tval += chr(self.ch)')

        g.copy_frame_part('-->comments')
        com: Comment = self.first_comment
        com_idx: int = 0
        while com is not None:
            self.gen_comment(com, com_idx)
            com = com.next
            com_idx += 1

        g.copy_frame_part('-->casing3')
        if self.ignore_case:
            self.println('\t\tval = val.lower()')

        g.copy_frame_part('-->scan1')
        self.print('\t\t\t')
        if self.tab.ignored.elements() > 0:
            self.put_range(self.tab.ignored)
        else:
            self.print('False')
        self.println(':')

        g.copy_frame_part('-->scan2')
        if self.first_comment is not None:
            self.print('\t\tif ')
            com = self.first_comment
            com_idx = 0
            while com is not None:
                self.print(self.ch_cond(ord(com.start[0])))
                self.print(' and  self.comment{}()'.format(com_idx))
                if com.next is not None:
                    self.print(' or ')

                com = com.next
                com_idx += 1

            self.println(':')
            self.println('\t\t\treturn self.next_token()')

        if self.has_ctx_moves:
            self.println()
            self.println('\t\tapx: int = 0')  # pdt

        g.copy_frame_part('-->scan3')
        for state in self.states():
            self.write_state(state)

        g.copy_frame_part(None)
        self.gen.close()
