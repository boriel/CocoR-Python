# -*- coding: utf-8 -*-

from typing import Optional, List


class State:
    nr: int  # State number

    def __init__(self):
        self.firstAction = None
        self.endOf = None
        self.ctx = False
        self.next = None
