# -*- coding: utf-8 -*-

from typing import NamedTuple


class Position(NamedTuple):
    beg: int
    end: int
    col: int
    line: int
