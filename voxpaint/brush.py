from functools import lru_cache

import numpy as np


class Brush:

    def __init__(self, size):
        assert len(size) == 2
        self.size = w, h = size
        self.center = (w // 2, h // 2)
        self.data = np.ones(size, dtype=np.uint32)

    @lru_cache(2)
    def get_draw_data(self, color):
        rgba_color = color + 255 * 2**24
        return self.data * rgba_color
