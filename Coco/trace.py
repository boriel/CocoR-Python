# -*- coding: utf-8 -*-

import os

from .errors import FatalError


class Trace:
    def __init__(self, dir_: str):
        fpath = os.path.join(dir_, 'trace.txt')
        try:
            self.file = open(fpath, mode='wt', encoding='utf-8')
        except BaseException:
            raise FatalError("Could not open {}".format(fpath))

    @staticmethod
    def format_string(s: str, w: int) -> str:
        """ Returns a string with a minimum length of |w| characters
        the string is left-adjusted if w < 0 and right-adjusted otherwise
        """
        if w < 0:
            return s.ljust(-w, ' ')
        return s.rjust(w, ' ')

    def write(self, s: str, w: int = None):
        if w is None:
            self.file.write(s)
        else:
            self.file.write(self.format_string(s, w))

    def write_line(self, s: str = '', w: int = None):
        self.write('{}\n'.format(s), w)

    def close(self):
        if self.file is not None:
            self.file.close()
            print("trace output is in {}".format(self.file.name))
            self.file = None
