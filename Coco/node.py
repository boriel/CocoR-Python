# -*- coding: utf-8 -*-

from typing import Optional

from .position import Position
from .state import State


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

    def __init__(self, typ: int, sym, line: int):
        self.n: int = 0
        self.next: Optional[Node] = None
        self.down: Optional[Node] = None
        self.sub: Optional[Node] = None
        self.up = False
        self.val = 0
        self.code = 0
        self.set = None
        self.pos: Optional[Position] = None
        self.state: Optional[State] = None
        self.typ = typ
        self.sym = sym
        self.line = line
