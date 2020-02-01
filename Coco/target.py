# -*- coding: utf-8 -*-

from typing import Optional

from .state import State


class Target:
    def __init__(self, state: State):
        self.state = state
        self.next: Optional[Target] = None
