# -*- coding: utf-8 -*-

from typing import Any, List


class ArrayList:
    def __init__(self):
        self.data = []

    def add(self, value: Any):
        self.data.append(value)

    def remove(self, value: Any):
        try:
            self.data.pop(self.data.index(value))
        except ValueError:
            pass

    def __getitem__(self, index) -> Any:
        if 0 <= index < len(self.data):
            return self.data[index]

        return None
