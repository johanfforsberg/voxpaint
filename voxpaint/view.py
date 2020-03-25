from functools import lru_cache
import math
from threading import RLock
from typing import Tuple, Optional

from euclid3 import Vector3
import numpy as np

from .brush import ImageBrush
from .draw import draw_line, draw_rectangle, blit
from .rect import Rectangle
from .util import AutoResetting


class DrawingView:

    """
    A particular "view" of a drawing. As of now only 90 degree rotations are supported.
    Most access to a drawing should be through a view.
    """

    layer_being_switched = AutoResetting(False)
    
    def __init__(self, drawing, rotation=(0, 0, 0)):
        self.drawing = drawing  # The underlying data
        self.rotation = rotation  # The transform
        self.cursor = (0, 0, 0)  # Position of the "current" layer in each dimension
        
        self.show_only_current_layer = False

    def rotate(self, dx=0, dy=0, dz=0):
        pitch, yaw, roll = self.rotation
        self.rotation = (pitch + dx) % 4, (yaw + dy) % 4, (roll + dz) % 4

    def move_cursor(self, dx=0, dy=0, dz=0):
        x, y, z = self.cursor
        w, h, d = self.drawing.data.shape
        self.cursor = (min(w-1, max(0, x + dx)),
                       min(h-1, max(0, y + dy)),
                       min(d-1, max(0, z + dz)))

    def set_cursor(self, x=None, y=None, z=None):
        x0, y0, z0 = self.cursor
        self.cursor = (x if x is not None else x0,
                       y if y is not None else y0,
                       z if z is not None else z0)
        self.layer_being_switched = True

    def layer_visible(self, index):
        if index == self.layer_index:
            return True
        return not self.show_only_current_layer and not self.layer_being_switched
        
    @property
    def data(self):
        return self._get_data(self.rotation)

    @lru_cache(1)
    def _get_data(self, rotation: Tuple[int, int, int]):
        " Return a ndarray view on the drawing data, rotated properly. "
        data = self.drawing.data
        rx, ry, rz = rotation
        # TODO this seems correct at least for the limited rotating we currently do...
        # But do figure out a more elegant way.
        if rz:
            data = np.rot90(data, rz, (0, 1))
        if rx:
            data = np.rot90(data, rx, (1, 2))
        if ry:
            data = np.rot90(data, ry, (2, 0))
        return data
                    
    @property
    def direction(self):
        return self._get_direction(self.rotation)

    @lru_cache(1)
    def _get_direction(self, rotation: Tuple[int, int, int]):
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
    
    @property
    def shape(self):
        return self.data.shape

    @property
    def size(self):
        return self.data.shape[:2]

    @property
    def depth(self):
        return self.data.shape[2]    
    
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
    def layers(self):
        d = self.shape[2]
        return (self.layer(i) for i in range(d))
                    
    @property
    def overlay(self):
        """
        The overlay is a temporary layer that is used for drawing in real time.
        When an operation is done (e.g. a pencil stroke) the overlay is copied
        into the drawing data (via an Edit, to make it undoable).
        """
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

    def modify(self, slc3: Tuple[slice, slice, slice], data, tool):
        self.drawing.modify(slc3, data, self.rotation, tool)

    def modify_layer(self, index, slc2, data, tool):
        self.drawing.modify((*slc2, slice(index, index+1)), data.reshape(*data.shape, 1), self.rotation, tool)
        
    def undo(self):
        self.drawing.undo()
        self._get_dirty.cache_clear()

    def redo(self):
        self.drawing.redo()
        self._get_dirty.cache_clear()

    def next_layer(self):
        x, y, z = self.direction
        self.move_cursor(x, y, z)
        self.layer_being_switched = True

    def prev_layer(self):
        x, y, z = self.direction
        self.move_cursor(-x, -y, -z)
        self.layer_being_switched = True

    def move_layer(self, d: int):
        from_index = self.layer_index
        to_index = from_index + d
        depth = self.data.shape[2]
        if (from_index != to_index) and (0 <= from_index < depth) and (0 <= to_index < depth):
            self.drawing.move_layer(from_index, to_index, self.rotation)
            deltas = [d * a for a in self.direction]
            self.move_cursor(*deltas)
            self.dirty[from_index] = self.dirty[to_index] = True  # TODO make this smarter

    def make_brush(self, rect: Optional[Rectangle]=None, clear: bool=False):
        if rect:
            print(rect)
            data = self.layer()[rect.as_slice()].copy()
        else:
            data = self.layer().copy()
        brush = ImageBrush(data=data)
        self.drawing.brushes.append(brush)
        
        
class Overlay:

    "A temporary 'layer' used for realtime preview of changes."
    
    def __init__(self, size: Tuple[int, int]):
        self.size = size
        self.data = np.zeros(size, dtype=np.uint32)

        self.lock = RLock()  # It is very important to grab this lock around all data changes!
        self.rect = Rectangle((0, 0), size)
        
        self.dirty = None

    def clear_all(self):
        self.clear(self.rect)
        
    def clear(self, rect: Rectangle):
        rect = self.rect.intersect(rect)
        if rect:
            x0, y0, x1, y1 = rect.box()
            with self.lock:
                self.data[x0:x1, y0:y1] = 0
            self.dirty = rect.unite(self.dirty)
        return rect

    def blit_brush(self, brush, p, color=0):
        x, y = p
        dx, dy = brush.center
        # dx, dy = 0, 0
        data = brush.get_draw_data(color)
        return self.blit(data, (int(x - dx), int(y - dy)))

    def blit(self, data: np.ndarray, p: Tuple[int, int]):
        x, y = p
        with self.lock:
            rect = blit(self.data, data, x, y)
        self.dirty = rect.unite(self.dirty)
        return rect
    
    def draw_line(self, brush, p0, p1, color=0):
        x0, y0 = p0
        x1, y1 = p1
        dx, dy = brush.center
        data = brush.get_draw_data(color)
        with self.lock:
            rect = draw_line(self.data, data, (int(x0-dx), int(y0-dy)), (int(x1-dx), int(y1-dy)))
        self.dirty = rect.unite(self.dirty)
        return rect

    def draw_rectangle(self, brush, pos, size, color=0, fill=False):
        x, y = pos
        dx, dy = brush.center
        data = brush.get_draw_data(color)
        with self.lock:
            rect = draw_rectangle(self.data, data, (x-dx, y-dy), size, color + 2**24, fill)
        if rect:
            self.dirty = rect.unite(self.dirty)
        return rect

    # TODO to be implemented
    # def draw_ellipse(self, brush, pos, size, color=0, fill=False):
    #     pass

    def shift(self, dx=0, dy=0, dz=0):
        data = self.data.copy()
        self.data = 0
        x, y, z = self.shape
        #self.data[max(0, dx):min(x, x+dx), max(0, dy):min(y, y+dy), max(0, dz):min(z, z+dz)] +=
        
        #self.modify(0, data[max(0, -dx):min(x, x-dx), max(0, -dy):max(y, y-dy), max(0, -dz):max(z, z-dz)]
