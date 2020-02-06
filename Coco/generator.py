# -*- coding: utf-8 -*-


__all__ = ['Generator']

import os
from typing import BinaryIO, TextIO, Optional

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
    gen: TextIO

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

    def open_gen(self, target: str) -> TextIO:
        f = os.path.join(self.tab.outDir, target)
        if os.path.exists(f):
            old = f + '.old'
            if os.path.exists(old):
                os.unlink(old)
            os.rename(f, old)

        try:
            self.gen = open(f, 'wt', encoding='utf-8')
        except OSError:
            raise FatalError("Cannot generate file: {}".format(f))

        return self.gen

    def gen_copyright(self):
        copy_fr = None
        if self.tab.frameDir is not None:
            copy_fr = os.path.join(self.tab.frameDir, 'copyright.frame')

        if copy_fr is None or not os.path.exists(copy_fr):
            copy_fr = os.path.join(self.tab.srcDir, 'copyright.frame')

        if copy_fr is None or not os.path.isfile(copy_fr):
            return

        try:
            scanner_fram: BinaryIO = self.fram
            self.fram = open(copy_fr, 'bt')
            self.copy_frame_part(None)
            self.fram = scanner_fram
        except OSError:
            raise FatalError("Cannot open copyright.frame")

    def skip_frame_part(self, stop: str):
        self.copy_frame_part(stop, False)

    # if stop == null, copies until end of file
    def copy_frame_part(self, stop: Optional[str], generate_output: bool = True):
        start_ch = 0
        end_of_stop_string = 0
        stop_ch = bytes(stop.encode('utf-8'))

        if stop:
            start_ch = stop_ch[0]
            end_of_stop_string = len(stop) - 1

        ch = self.fram_read()
        while ch != self.EOF:
            if stop and ch == start_ch:
                i = 0
                while ch == stop_ch[i]:
                    if i == end_of_stop_string:
                        return
                    ch = self.fram_read()
                    i += 1

                if generate_output:
                    self.gen.write(stop[0:i])
            else:
                if generate_output:
                    self.gen.write(chr(ch))
                    ch = self.fram_read()

        if stop:
            raise FatalError("Incomplete or corrupt frame file: {}". format(self.frame_file))

    def fram_read(self) -> int:
        try:
            result = self.fram.read(1)
        except OSError:
            raise FatalError("Error reading frame file: {}".format(self.frame_file))

        if not result:
            return self.EOF

        return result[0]
