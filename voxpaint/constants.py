from enum import Enum

import numpy as np


class ToolName(Enum):
    pencil = 1
    points = 2
    spray = 3
    line = 4
    rectangle = 5
    ellipse = 6
    floodfill = 7
    brush = 8
    picker = 9


Rx90 = np.matrix([[1, 0, 0, 0],
                  [0, 0, 1, 0],
                  [0, -1, 0, 0],
                  [0, 0, 0, 1]])
Ry90 = np.matrix([[0, 0, -1, 0],
                  [0, 1, 0, 0],
                  [1, 0, 0, 0],
                  [0, 0, 0, 1]])
Rz90 = np.matrix([[0, 1, 0, 0],
                  [-1, 0, 0, 0],
                  [0, 0, 1, 0],
                  [0, 0, 0, 1]])

