# -*- coding: utf-8 -*-


__all__ = ['Generator']

import os
from typing import BinaryIO

from .tab import Tab
from .errors import FatalError


# -----------------------------------------------------------------------------
#  Generator
# -----------------------------------------------------------------------------
class Generator:
    EOF = -1
    tab: Tab
    frame_file: str
    fram: BinaryIO

    def __init__(self, tab: Tab):
        self.tab = tab

    def open_file(self, fname) -> BinaryIO:
        if self.tab.frameDir is not None:
            self.frame_file = os.path.join(self.tab.frameDir, fname)
            if not os.path.exists(self.frame_file):
                raise FatalError("Cannot find file {}".format(self.frame_file))

            if not os.path.isfile(self.frame_file):
                raise FatalError("'{}' is not a regular file".format(self.frame_file))

        try:
            self.fram = open(self.frame_file, 'rb')
        except OSError:
            raise FatalError("Cannot open file: {}".format(self.frame_file))

        return self.fram
