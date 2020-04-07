from functools import lru_cache
import math
from threading import RLock
from time import time
from typing import Tuple, Optional

from euclid3 import Vector3
import numpy as np

from .brush import Brush, ImageBrush
from .draw import draw_line, draw_rectangle, blit
from .rect import Rectangle
from .util import AutoResetting


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


def make_translation(x, y, z):
    return np.matrix([[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]])


class DrawingView:

    """
    A particular "view" of a drawing. Most access to a drawing should be through
    a view.
    
    The view holds most of the application state related to a drawing, like
    zoom and pan offset, as well as layer visibility.

    It can also apply transformations to the drawing. As of now only 90 degree
    rotations are supported. 
    
    A "layer" is only meaningful in the context of a given view, and refers to
    slices of the drawing perpendicular to the current "z" direction. 
    """

    layer_being_switched = AutoResetting(False)
    
    def __init__(self, drawing, rotation=(0, 0, 0)):
        self.drawing = drawing  # The underlying data
        self.rotation = rotation  # The transform
        self.cursor = (0, 0, 0)  # Position of the "current" layer in each dimension

        self.offset = (0, 0)
        self.zoom = 2
        
        self.show_only_current_layer = False

    def rotate(self, dx: int=0, dy: int=0, dz: int=0):
        "Rotation is given in whole multiples of 90 degrees."
        pitch, yaw, roll = self.rotation
        self.rotation = (pitch + dx) % 4, (yaw + dy) % 4, (roll + dz) % 4

    def set_cursor(self, x=None, y=None, z=None):
        print("set_cursor", x, y, z)
        x0, y0, z0 = self.cursor
        self.cursor = (x if x is not None else x0,
                       y if y is not None else y0,
                       z if z is not None else z0)
        self.layer_being_switched = True
        
    def move_cursor(self, dx=0, dy=0, dz=0):
        "Move the cursor relative to current position."
        print("move_cursor", dx, dy, dz)
        x, y, z = self.cursor
        w, h, d = self.drawing.data.shape
        self.cursor = (min(w-1, max(0, x + dx)),
                       min(h-1, max(0, y + dy)),
                       min(d-1, max(0, z + dz)))
        
    @property
    def data(self):
        return self._get_data(self.drawing.data.shape, self.rotation)

    @lru_cache(1)
    def _get_data(self, shape: Tuple[int, int, int], rotation: Tuple[int, int, int]):
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
        # Layer visibility is implemented using a masked array. This makes it
        # pretty much transparent (ho ho) to the rest of the application.
        return data

    def _unrotate_array(self, a, rotation):
        rx, ry, rz = rotation
        print(a.shape)
        if ry:
            a = np.rot90(a, -ry, (2, 0))
        if rx:
            a = np.rot90(a, -rx, (1, 2))
        if rz:
            a = np.rot90(a, -rz, (0, 1))
        return a
    
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
        # TODO This is pretty crude. Also, use numpy instead of euclid?
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
        return self._get_layer_index(self.direction, self.data.shape, self.cursor)

    @lru_cache(1)
    def _get_layer_index(self, direction, shape, cursor):
        x, y, z = direction
        d = shape[2]
        cx, cy, cz = cursor
        if x:
            return cx if x == 1 else d - cx - 1
        if y:
            return cy if y == 1 else d - cy - 1
        if z:
            return cz if z == 1 else d - cz - 1        
        
    def layer(self, index: int=None):
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
        """
        return self._get_overlay(self.shape[:2])

    @lru_cache(3)
    def _get_overlay(self, size: Tuple[int, int]):
        return Overlay(size)

    def modify(self, slc3: Tuple[slice, slice, slice], data, tool):
        self.drawing.modify(slc3, data, self.rotation, tool)

    def next_layer(self):
        self.switch_layer(1)

    def prev_layer(self):
        self.switch_layer(-1)

    def switch_layer(self, delta):
        x, y, z = self.direction
        self.move_cursor(delta * x, delta * y, delta * z)
        self.layer_being_switched = True
        
    def modify_layer(self, index: int, rect: Rectangle, data: np.ndarray, tool):
        drawing_slice = self.to_drawing_slice(rect)
        data = data.reshape(*data.shape, 1)
        self.drawing.modify(drawing_slice, self._unrotate_array(data, self.rotation), tool)
                
    def move_layer(self, d: int):
        from_index = self.layer_index
        to_index = from_index + d
        depth = self.data.shape[2]
        if (from_index != to_index) and (0 <= from_index < depth) and (0 <= to_index < depth):
            rect = Rectangle(size=self.size)
            slc1 = self.to_drawing_slice(rect, from_index)
            slc2 = self.to_drawing_slice(rect, to_index)
            self.drawing.move_layer(slc1, slc2)
            deltas = [d * a for a in self.direction]
            self.move_cursor(*deltas)

    def delete_layer(self, index=None, axis=0):
        index = self.layer_index if index is None else index
        axis = [abs(d) for d in self.direction].index(1)  # TODO this is stupid
        self.drawing.delete_layers(index, axis, 1)

    def insert_layer(self, index=None, axis=0):
        index = self.layer_index if index is None else index
        axis = [abs(d) for d in self.direction].index(1)  # TODO this is stupid
        self.drawing.insert_layers(index, axis, 1)

    def duplicate_layer(self, index=None, axis=0):
        index = self.layer_index if index is None else index
        axis = [abs(d) for d in self.direction].index(1)  # TODO this is stupid
        self.drawing.duplicate_layer(index, axis)
        
    def make_brush(self, rect: Optional[Rectangle]=None, clear: bool=False):
        if rect:
            data = self.layer()[rect.as_slice()].copy()
        else:
            data = self.layer().copy()
        brush = ImageBrush(data=data)
        self.drawing.brushes.append(brush)

    @property
    def untransform(self):
        return self._get_untransform(self.rotation)

    @lru_cache(1)
    def _get_untransform(self, rotation):
        w1, h1, d1 = self.shape
        T1 = make_translation(-w1 / 2, -h1 / 2, -d1 / 2)
        print("T1", T1)
        w2, h2, d2 = self.data.base.shape if self.data.base is not None else self.shape
        T2 = make_translation(w2 / 2, h2 / 2, d2 / 2)
        print("T2", T2)
        R = np.matrix(np.eye(4))
        rx, ry, rz = rotation
        for _ in range(rz):
            R *= Rz90
        for _ in range(rx):
            R *= Rx90
        for _ in range(ry):
            R *= Ry90
        print("R", R)
        return T2 * R * T1

    def to_drawing_slice(self, rect, index=None):
        x0, y0 = rect.topleft
        x1, y1 = rect.bottomright

        index = self.layer_index if index is None else index
        topleft = np.array([x0, y0, index, 1])
        bottomright = np.array([x1, y1, index+1, 1])

        T = self.untransform
        print((T @ topleft.T).getA1())
        xd0, yd0, zd0, _ = (T @ topleft.T).getA1()
        xd1, yd1, zd1, _ = (T @ bottomright.T).getA1()

        return (slice(*sorted([int(xd0), int(xd1)])),
                slice(*sorted([int(yd0), int(yd1)])),
                slice(*sorted([int(zd0), int(zd1)])))
        
            
class Overlay:

    """
    A temporary 'layer' used for realtime preview of changes. Drawing strokes
    happen in an overlay until they are finished, and then the data is transfered
    to the current layer, via an Edit.
    """
    
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

    def blit_brush(self, brush, p: Tuple[int, int], color: int=0):
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
    
    def draw_line(self, brush: Brush, p0: Tuple[int, int], p1: Tuple[int, int], color: int=0):
        x0, y0 = p0
        x1, y1 = p1
        dx, dy = brush.center
        data = brush.get_draw_data(color)
        with self.lock:
            rect = draw_line(self.data, data, (int(x0-dx), int(y0-dy)), (int(x1-dx), int(y1-dy)))
        self.dirty = rect.unite(self.dirty)
        return rect

    def draw_rectangle(self, brush: Brush, pos, size, color=0, fill=False):
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
