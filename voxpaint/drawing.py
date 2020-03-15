from functools import lru_cache
from typing import Optional, Tuple, List
import math
from threading import RLock

import numpy as np
from euclid3 import Vector3

from .draw import draw_line
from .edit import Edit
from .ora import load_ora
from .palette import Palette
from .rect import Rectangle


Shape = Tuple[int, ...]
        

class Drawing:

    def __init__(self, size:Optional[Shape]=None, data:Optional[np.ndarray]=None, palette:Palette=None):
        if data is not None:
            self.data = data
        elif size:
            if len(size) == 2:
                shape = (*size, 1)
            elif len(size) == 3:
                shape = size
            self.data = np.zeros(shape, dtype=np.uint8)
        self.palette = palette

        self.lock = RLock()

        self.undos = []
        self.redos = []

    @classmethod
    def from_ora(cls, path):
        data, info, _ = load_ora(path)
        print(data)
        return cls(data=data, palette=Palette(info["palette"]))

    def modify(self, index, slc, data, rotation, tool):
        # TODO This seems a little over complicated; seems like it
        # should be possible to find the slice in the original data to
        # use.
        view = DrawingView(self, rotation=rotation)
        layer = view.layer(index)
        edit = Edit.create(index, slc, rotation, layer, data, tool)
        self.undos.append(edit)
        np.copyto(layer[slc], data, where=data > 255)
        
    def undo(self):
        try:
            edit = self.undos.pop()
            self.redos.append(edit)
            edit.revert(self)
        except IndexError:
            pass

    def redo(self):
        try:
            edit = self.redos.pop()
            self.undos.append(edit)
            edit.perform(self)
        except IndexError:
            pass

    def get_view(self, rotation):
        return DrawingView(self, rotation)
        
    
class DrawingView:

    def __init__(self, drawing, rotation=(0, 0, 0)):
        self.drawing = drawing
        self.rotation = rotation
        self.cursor = (0, 0, 0)

    def rotate(self, dx=0, dy=0, dz=0):
        pitch, yaw, roll = self.rotation
        self.rotation = (pitch + dx) % 4, (yaw + dy) % 4, (roll + dz) % 4

    def move_cursor(self, dx=0, dy=0, dz=0):
        x, y, z = self.cursor
        w, h, d = self.drawing.data.shape
        self.cursor = (min(w-1, max(0, x + dx)),
                       min(h-1, max(0, y + dy)),
                       min(d-1, max(0, z + dz)))
        
    @property
    def data(self):
        return self._get_view(self.rotation)

    @property
    def direction(self):
        return self._get_direction(self.rotation)

    @lru_cache(1)
    def _get_direction(self, rotation):
        """
        Return a vector pointing in the positive direction of the current view.
        That means the direction in which the layer structure is stacked,
        i.e. "up". The "layer_index" tells where along this axis the cursor is.
        """
        rx, ry, rz = rotation
        v = Vector3(0, 0, 1)
        zaxis = Vector3(0, 0, 1)
        xaxis = Vector3(1, 0, 0)
        yaxis = Vector3(0, 1, 0)
        if ry:
            v = v.rotate_around(yaxis, -ry * math.pi/2)
        if rx:
            v = v.rotate_around(xaxis, -rx * math.pi/2)        
        if rz:
            v = v.rotate_around(zaxis, -rz * math.pi/2)
        return tuple(int(a) for a in v)
    
    @lru_cache(1)
    def _get_view(self, rotation):
        data = self.drawing.data
        rx, ry, rz = rotation
        if rz:
            data = np.rot90(data, rz, (0, 1))
        if rx:
            data = np.rot90(data, rx, (1, 2))
        if ry:
            data = np.rot90(data, ry, (2, 0))
        return data
                
    @property
    def shape(self):
        return self.data.shape

    @property
    def size(self):
        return self.data.shape[:2]

    @property
    def layer_index(self):
        "The depth of the current layer index as seen from the user."
        x, y, z = self.direction
        d = self.data.shape[2]
        cx, cy, cz = self.cursor
        if x:
            return cx if x == 1 else d - cx - 1
        if y:
            return cy if y == 1 else d - cy - 1
        if z:
            return cz if z == 1 else d - cz - 1

    def layer(self, index=None):
        index = index if index is not None else self.layer_index
        return self.data[:, :, index]
                    
    @property
    def overlay(self):
        "The overlay is a temporary layer that is used for drawing."
        return self._get_overlay(self.shape[:2])

    @lru_cache(3)
    def _get_overlay(self, size):
        return Overlay(size)

    @property
    def dirty(self):
        "A dict of the current 'dirty' parts of each layer by index."
        return self._get_dirty(self.rotation)

    @lru_cache(1)
    def _get_dirty(self, rot):
        w, h, d = self.shape
        rect = Rectangle(size=(w, h))
        return {index: rect for index in range(d)}

    def modify(self, index, slc, data, tool):
        self.drawing.modify(index, slc, data, self.rotation, tool)

    def undo(self):
        self.drawing.undo()
        self._get_dirty.cache_clear()

    def redo(self):
        self.drawing.redo()
        self._get_dirty.cache_clear()

    def next_layer(self):
        x, y, z = self.direction
        self.move_cursor(x, y, z)        

    def prev_layer(self):
        x, y, z = self.direction
        self.move_cursor(-x, -y, -z)        
        
        
class Overlay:

    def __init__(self, size):
        self.size = size
        self.data = np.zeros(size, dtype=np.uint32)
        self.dirty = None
        self.lock = RLock()
        self.brush_preview_dirty = None

    def clear(self, rect=None):
        if rect:
            x0, y0, x1, y1 = rect.box()
        else:
            x0, y0, x1, y1 = 0, 0, *self.size
            rect = Rectangle((x0, y0), (x1-x0, y1-y0))
        self.data[x0:x1, y0:y1] = 0
        self.dirty = rect.unite(self.dirty)

    def blit(self, data, rect):
        #self.data[rect.as_slice()] = data
        #self.dirty = rect.unite(self.dirty)
        pass
        
    def draw_line(self, brush, p0, p1, color=0):
        x0, y0 = p0
        x1, y1 = p1
        dx, dy = brush.center
        data = brush.get_draw_data(color)
        rect = draw_line(self.data, (x0-dx, y0-dy), (x1-dx, y1-dy), data)
        self.dirty = rect.unite(self.dirty)
        return rect
