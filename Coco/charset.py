# -*- coding: utf-8 -*-

from typing import List

from .constants import COCO_WCHAR_MAX


class Range:
    def __init__(self, from_: int, to: int):
        self.from_ = from_
        self.to = to

    def __len__(self):
        return self.to - self.from_ + 1

    def __getitem__(self, item) -> int:
        if self.from_ <= item <= self.to:
            return item
        raise IndexError("out of range")

    def __iter__(self):
        for i in range(self.from_, self.to + 1):
            yield i

    def __eq__(self, other):
        assert isinstance(other, Range)
        return self.from_, self.to == other.from_, other.to


class CharSet:
    def __init__(self):
        self.ranges: List[Range] = []

    def get(self, i: int) -> bool:
        for p in self.ranges:
            if i < p.from_:
                return False
            if i <= p.to:
                return True

        return False

    def set(self, i: int):
        jj = 0
        for jj, cur in enumerate(self.ranges):
            if i >= cur.from_ - 1:
                break

            if i <= cur.to + 1:
                if i == cur.from_ - 1:
                    cur.from_ -= 1
                elif i == cur.to + 1:
                    cur.to += 1
                    if jj + 1 < len(self.ranges):
                        next_ = self.ranges[jj + 1]
                        if cur.to == next_.from_ - 1:
                            cur.to = next_.to
                            self.ranges.pop(jj + 1)
                            continue
            return

        self.ranges.insert(jj, Range(i, i))

    def clone(self):
        result = CharSet()
        for range_ in self.ranges:
            result.ranges.append(Range(range_.from_, range_.to))

        return result

    def equals(self, other) -> bool:
        assert isinstance(other, CharSet)
        return self.ranges == other.ranges

    def elements(self) -> int:
        return sum(len(p) for p in self.ranges)

    def first(self) -> int:
        return self.ranges[0].from_ if self.ranges else -1

    def or_(self, other: 'CharSet'):
        assert isinstance(other, CharSet)
        for range_ in other.ranges:
            for i in range_:
                self.set(i)

    def and_(self, other):
        assert isinstance(other, CharSet)
        x = CharSet()

        for range_ in self.ranges:
            for i in range_:
                if other.get(i):
                    x.set(i)

        self.ranges = x.ranges

    def subtract(self, other):
        assert isinstance(other, CharSet)
        x = CharSet()

        for range_ in self.ranges:
            for i in range_:
                if not other.get(i):
                    x.set(i)

        self.ranges = x.ranges

    def includes(self, other) -> bool:
        assert isinstance(other, CharSet)
        return all(
            all(self.get(i) for i in range_)
            for range_ in other.ranges
        )

    def intersects(self, other) -> bool:
        assert isinstance(other, CharSet)
        return any(
            any(self.get(i) for i in range_)
            for range_ in other.ranges
        )

    def fill(self):
        self.ranges = [Range(0, COCO_WCHAR_MAX)]
