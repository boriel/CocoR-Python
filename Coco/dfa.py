# -*- coding: utf-8 -*-

from typing import List, Optional

from .tab import Node, Symbol, Tab, CharClass
from .charset import CharSet


class Target:
    def __init__(self, state: 'State'):
        self.state = state


class Comment:
    next: 'Comment'

    def __init__(self, start: str, stop: str, nested: bool):
        self.start = start
        self.stop = stop
        self.nested = nested


class Action:
    def __init__(self, typ: int, sym: int, tc: int):
        self.typ = typ
        self.sym = sym
        self.tc = tc
        self.target: List[Target] = []

    def add_target(self, t: Target):
        i = 0
        for i, p in enumerate(self.target):
            if p.state == t.state:
                return
            if t.state.nr < p.state.nr:
                break

        self.target.insert(i, t)

    def add_targets(self, a):
        assert isinstance(a, Action)
        for t in a.target:
            self.add_target(Target(t.state))

        if a.tc == Node.contextTrans:
            self.tc = Node.contextTrans

    def symbols(self, tab: Tab) -> CharSet:
        if self.typ == Node.clas:
            s = tab.char_class_set(self.sym).clone()
        else:
            s = CharSet()
            s.set(self.sym)
        return s

    def shift_with(self, s: CharSet, tab: Tab):
        if s.elements() == 1:
            self.typ = Node.chr
            self.sym = s.first()
        else:
            c = tab.find_char_class(s)
            if c is None:
                c = tab.new_char_class('#', s)
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


class Melted:
    def __init__(self, set_: set, state: State):
        self.set_ = set_
        self.state = state


class DFA:
    pass
