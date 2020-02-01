# -*- coding: utf-8 -*-

import sys
from typing import TextIO


class Errors:
    count: int = 0
    errorStream: TextIO = sys.stderr
    errMsgFormat: str = "-- line {0} col {1}: {2}"

    def _print_msg(self, line: int, column: int, msg: str):
        self.errorStream.write(self.errMsgFormat.format(line, column, msg))

    def sym_err(self, line: int, col: int, n: int):
        errors = {
            0: "EOF expected",
            1: "ident expected",
            2: "number expected",
            3: "string expected",
            4: "badString expected",
            5: "char expected",
            6: "\"COMPILER\" expected",
            7: "\"IGNORECASE\" expected",
            8: "\"CHARACTERS\" expected",
            9: "\"TOKENS\" expected",
            10: "\"PRAGMAS\" expected",
            11: "\"COMMENTS\" expected",
            12: "\"FROM\" expected",
            13: "\"TO\" expected",
            14: "\"NESTED\" expected",
            15: "\"IGNORE\" expected",
            16: "\"PRODUCTIONS\" expected",
            17: "\"=\" expected",
            18: "\".\" expected",
            19: "\"END\" expected",
            20: "\"+\" expected",
            21: "\"-\" expected",
            22: "\"..\" expected",
            23: "\"ANY\" expected",
            24: "\"<\" expected",
            25: "\"^\" expected",
            26: "\"out\" expected",
            27: "\">\" expected",
            28: "\",\" expected",
            29: "\"<.\" expected",
            30: "\".>\" expected",
            31: "\"[\" expected",
            32: "\"]\" expected",
            33: "\"|\" expected",
            34: "\"WEAK\" expected",
            35: "\"(\" expected",
            36: "\")\" expected",
            37: "\"{\" expected",
            38: "\"}\" expected",
            39: "\"SYNC\" expected",
            40: "\"IF\" expected",
            41: "\"CONTEXT\" expected",
            42: "\"(.\" expected",
            43: "\".)\" expected",
            44: "??? expected",
            45: "this symbol not expected in Coco",
            46: "this symbol not expected in TokenDecl",
            47: "invalid TokenDecl",
            48: "invalid AttrDecl",
            49: "invalid AttrDecl",
            50: "invalid AttrDecl",
            51: "invalid AttrDecl",
            52: "invalid AttrDecl",
            53: "invalid SimSet",
            54: "invalid Sym",
            55: "invalid Term",
            56: "invalid Factor",
            57: "invalid Attribs",
            58: "invalid Attribs",
            59: "invalid Attribs",
            60: "invalid Attribs",
            61: "invalid Attribs",
            62: "invalid TokenFactor",
            63: "invalid Bracketed",
        }

        s = errors.get(n, "error {}".format(n))
        self._print_msg(line, col, s)
        self.count += 1

    def sem_err(self, *args):
        self.count += 1
        self.warning(*args)

    def warning(self, *args):
        assert len(args) in (1, 3)
        if len(args) == 3:
            self._print_msg(*args)
        else:
            self.errorStream.write('{}\n'.format(args[0]))


class FatalError(RuntimeError):
    pass
