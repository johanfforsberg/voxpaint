from itertools import chain
from functools import lru_cache
import json
from typing import List, Tuple, Optional


with open("palettes/vga_palette.json") as f:
    vga_palette = json.load(f)


DEFAULT_COLORS = [(r, g, b, 255 * (i != 0))
                  for i, (r, g, b)
                  in enumerate(vga_palette)]
    

Color = Tuple[int, int, int, int]


class Palette:

    def __init__(self, colors: Tuple[Color]=DEFAULT_COLORS):
        self.size = 256
        self._colors = tuple(colors) + ((0, 0, 0, 255),) * (self.size - len(colors))
        self.version = 0
        self.overlay = None

        self.foreground = 1
        self.background = 0

        self.overlay = {}

    def __hash__(self):
        return hash((id(self), self.version))

    @property
    def foreground_color(self):
        return self.colors[self.foreground]

    @property
    def background_color(self):
        return self.colors[self.background]    
        
    @property
    def colors(self):
        return self._get_overlayed_colors()

    @lru_cache(256)
    def _get_overlayed_colors(self):
        return tuple(self.overlay.get(i, self._colors[i])
                     for i in range(self.size))

    def set_overlay(self, i: int, color: Color):
        self.overlay[i] = color
        self._get_overlayed_colors.cache_clear()

    def clear_overlay(self):
        self.overlay.clear()
        self._get_overlayed_colors.cache_clear()

    def set_colors(self, start_i: int, colors: Tuple[Color]):
        n = len(colors)
        self._colors = self._colors[:start_i] + colors + self._colors[start_i+n:]
        self._get_overlayed_colors.cache_clear()
        
    
    
