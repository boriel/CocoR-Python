# -*- coding: utf-8 -*-

from typing import List, Optional

from .node import Node
from .target import Target


class Action:
    def __init__(self, typ: int, sym: int, tc: int):
        self.typ = typ
        self.sym = sym
        self.tc = tc

        self.target: List[Target] = []
        self.next: Optional[Action] = None

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
