from functools import lru_cache
from typing import List, Tuple, Optional


DEFAULT_COLORS = [
    (170,170,170,0),(255,255,255,255),(101,101,101,255),(223,223,223,255),(207,48,69,255),
    (223,138,69,255),(207,223,69,255),(138,138,48,255),(48,138,69,255),(69,223,69,255),
    (69,223,207,255),(48,138,207,255),(138,138,223,255),(69,48,207,255),(207,48,207,255),
    (223,138,207,255),(227,227,227,255),(223,223,223,255),(223,223,223,255),(195,195,195,255),
    (178,178,178,255),(170,170,170,255),(146,146,146,255),(130,130,130,255),(113,113,113,255),
    (113,113,113,255),(101,101,101,255),(81,81,81,255),(65,65,65,255),(48,48,48,255),
    (32,32,32,255),(32,32,32,255),(243,0,0,255)
];

Color = Tuple[int, int, int, int]


class Palette:

    def __init__(self, colors: List[Color]=DEFAULT_COLORS):
        self.size = 256
        self.colors = colors + [(0, 0, 0, 255)] * (self.size - len(colors))
        self.version = 0
        self.overlay = None

        self.foreground = 1
        self.background = 0

        self.overlay = ()

    def __hash__(self):
        return hash((id(self), self.version, self.overlay))

    @property
    def foreground_color(self):
        return self.colors[self.foreground]

    @property
    def background_color(self):
        return self.colors[self.background]    

    @lru_cache(maxsize=1)
    def as_tuple(self):
        return tuple(self.colors[i] for i in range(self.size))
        
