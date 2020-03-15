from functools import lru_cache

import numpy as np


class Brush:

    def __init__(self, size=None, data=None):
        if size:
            assert len(size) == 2
            self.size = size
            self.data = np.ones(size, dtype=np.uint32)
        else:
            self.data = data
            self.size = data.shape[:2]

        w, h = self.size
        self.center = (w // 2, h // 2)
            
    @lru_cache(2)
    def get_draw_data(self, color):
        rgba_color = color + 255 * 2**24
        return self.data * rgba_color
