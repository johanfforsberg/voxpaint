from functools import lru_cache
from itertools import chain
import math
from threading import RLock
from typing import Tuple, Optional

from euclid3 import Vector3
import numpy as np

from .brush import Brush, ImageBrush
from .constants import Rx90, Ry90, Rz90
from .draw import draw_line, draw_rectangle, blit
from .rect import Rectangle
from .util import AutoResetting


def make_translation(x, y, z):
    return np.matrix([[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]])


class DrawingView:

    """
    A particular "view" of a drawing. Most access to a drawing should be through
    a view, since that's how the user will see it.
    
    The view holds most of the application state related to a drawing, like
    zoom and pan offset. It can also apply transformations to the drawing.
    As of now only 90 degree rotations are supported. 
    
    A "layer" is only meaningful in the context of a given view, and refers to
    slices of the drawing perpendicular to the current "depth" direction. 
    """

    layer_being_switched = AutoResetting(False)
    
    def __init__(self, drawing, rotation=(0, 0, 0)):
        self.drawing = drawing  # The underlying data
        self.rotation = rotation  # The transform

        self.offset = (0, 0)
        self.zoom = 2
        
        self.show_only_current_layer = False

    def rotate(self, dx: int=0, dy: int=0, dz: int=0):
        "Rotation is given in whole multiples of 90 degrees."
        pitch, yaw, roll = self.rotation
        self.rotation = (pitch + dx) % 4, (yaw + dy) % 4, (roll + dz) % 4

    @property
    def cursor(self):
        return self.drawing.cursor

    def set_cursor(self, x=None, y=None, z=None, set_layer_being_switched=True):
        self.drawing.set_cursor(x, y, z)
        if set_layer_being_switched:
            self.layer_being_switched = True

    def move_cursor(self, dx=0, dy=0, dz=0, set_layer_being_switched=True):
        self.drawing.move_cursor(dx, dy, dz)
        if set_layer_being_switched:
            self.layer_being_switched = True
            
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
        i.e. "up". The "index" tells where along this axis the cursor is.
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
    def index(self):
        "The depth of the current layer index as seen from the user."
        return self._get_index(self.direction, self.data.shape, self.cursor)

    @lru_cache(1)
    def _get_index(self, direction, shape, cursor):
        self._get_index
        x, y, z = direction
        d = shape[2]
        cx, cy, cz = cursor
        if x:
            return cx if x == 1 else d - cx - 1
        if y:
            return cy if y == 1 else d - cy - 1
        if z:
            return cz if z == 1 else d - cz - 1        

    def index_of_layer(self, layer_i):
        if self.direction[self.axis] > 0:
            return layer_i
        else:
            return self.depth - 1 - layer_i
        
    def layer(self, index: int=None):
        index = index if index is not None else self.index
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

    def rotate_drawing(self, amount, axis=None):
        axis = axis if axis is not None else self.axis
        self.drawing.rotate(amount, axis)

    def flip_drawing(self, vertically=False):
        a1, a2 = self.axes
        for _ in range(self.rotation[self.axis]):
            a1, a2 = a2, a1
        self.drawing.flip((a1, a2)[vertically])
        
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
        from_index = self.index
        to_index = from_index + d
        depth = self.data.shape[2]
        if (from_index != to_index) and (0 <= from_index < depth) and (0 <= to_index < depth):
            self.drawing.move_layer(from_index, to_index, self.axis)
            deltas = [d * a for a in self.direction]
            self.move_cursor(*deltas)

    @property
    def axis(self):
        "The 'depth' axis."
        return self._get_axis(self.direction)
    
    @lru_cache(1)
    def _get_axis(self, direction):
        return [abs(d) for d in direction].index(1)  # TODO this is stupid

    @property
    def axes(self):
        "The two axes defining the 'plane' of the view."
        return self._get_axes(self.direction)

    @lru_cache(1)
    def _get_axes(self, direction):
        return tuple(chain(range(self.axis), range(self.axis + 1, 3)))
        
    def delete_layer(self, index=None):
        index = self.index if index is None else index
        
        self.drawing.delete_layers(index, self.axis, 1)

    def insert_layer(self, index=None):
        direction = sum(a for a in self.direction if a > 0)
        if direction:
            index = self.index + 1
        else:
            index = self.depth - self.index - 1
        if 0 <= index <= self.depth:
            self.drawing.insert_layers(index, self.axis, 1)
            self.move_cursor(dz=direction)

    def duplicate_layer(self, index=None):
        index = self.index if index is None else index
        self.drawing.duplicate_layer(index, self.axis)

    @property
    def hidden_layers(self):
        return self.drawing.hidden_layers_by_axis[self.axis]
        
    def hide_layer(self, index=None):
        index = self.cursor[self.axis] if index is None else index
        self.drawing.hide_layer(index, self.axis)

    def show_layer(self, index=None):
        index = self.cursor[self.axis] if index is None else index
        self.drawing.show_layer(index, self.axis)

    def layer_visible(self, index=None):
        return self.drawing.layer_visible(index, self.axis)
        
    def toggle_layer(self, index=None):
        index = self.cursor[self.axis] if index is None else index
        if self.layer_visible(index):
            self.hide_layer(index)
        else:
            self.show_layer(index)
        
    def make_brush(self, rect: Optional[Rectangle]=None, clear: bool=False):
        if rect:
            data = self.layer()[rect.as_slice()].copy()
        else:
            data = self.layer().copy()
        brush = ImageBrush(data=data)
        self.drawing.brushes.append(brush)

    @property
    def untransform(self):
        "This transform should take us from the view's space to the drawing's space."
        return self._get_untransform(self.shape, self.drawing.data.shape, self.rotation)

    @lru_cache(1)
    def _get_untransform(self, shape, drawing_shape, rotation):
        w1, h1, d1 = shape
        T1 = make_translation(-w1 / 2, -h1 / 2, -d1 / 2)
        w2, h2, d2 = drawing_shape
        T2 = make_translation(w2 / 2, h2 / 2, d2 / 2)
        R = np.matrix(np.eye(4))
        rx, ry, rz = rotation
        for _ in range(rz):
            R *= Rz90
        for _ in range(rx):
            R *= Rx90
        for _ in range(ry):
            R *= Ry90
        return T2 * R * T1

    def to_drawing_slice(self, rect, index=None):

        "Take a rect in the view's space and return a slice into the drawing data."

        # TODO I don't like this mess of 2d rects and 3d slices, clean it up.
        
        x0, y0 = rect.topleft
        x1, y1 = rect.bottomright

        index = self.index if index is None else index
        topleft = np.array([x0, y0, index, 1])
        bottomright = np.array([x1, y1, index+1, 1])

        T = self.untransform
        xd0, yd0, zd0, _ = (T @ topleft.T).getA1()
        xd1, yd1, zd1, _ = (T @ bottomright.T).getA1()

        return (slice(*sorted([int(xd0), int(xd1)])),
                slice(*sorted([int(yd0), int(yd1)])),
                slice(*sorted([int(zd0), int(zd1)])))

    def to_drawing_coord(self, x, y, z):
        "Return the given view point in drawing space."
        # Note: adding .5 to each dimension because we need to use pixel centers here.
        # Otherwise there will be offset problems with rotation.
        return [int(x) for x in (self.untransform @ (x + .5, y + .5, z + .5, 1)).getA1()][:3]
    
            
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
                             # Drawing is done in a thread and can otherwise collide with the main thread.
        self.rect = Rectangle((0, 0), size)
        
        self.dirty = None  # After an edit, set this to the covering rect. This informs the renderer
                           # that it should update its textures.

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

    def blit_brush(self, brush, p: Tuple[int, int], color: int=0, colorize: bool=False):
        x, y = p
        dx, dy = brush.center
        # dx, dy = 0, 0
        data = brush.get_draw_data(color, colorize)
        return self.blit(data, (int(x - dx), int(y - dy)))

    def blit(self, data: np.ndarray, p: Tuple[int, int]):
        x, y = p
        with self.lock:
            rect = blit(self.data, data, x, y)
        self.dirty = rect.unite(self.dirty)
        return rect
    
    def draw_line(self, brush: Brush, p0: Tuple[int, int], p1: Tuple[int, int], color: int=0, colorize: bool=False):
        x0, y0 = p0
        x1, y1 = p1
        dx, dy = brush.center
        data = brush.get_draw_data(color, colorize)
        with self.lock:
            rect = draw_line(self.data, data, (int(x0-dx), int(y0-dy)), (int(x1-dx), int(y1-dy)))
        self.dirty = rect.unite(self.dirty)
        return rect

    def draw_rectangle(self, brush: Brush, pos, size, color=0, fill=False, colorize: bool=False):
        x, y = pos
        dx, dy = brush.center
        data = brush.get_draw_data(color, colorize)
        with self.lock:
            rect = draw_rectangle(self.data, data, (x-dx, y-dy), size, color + 2**24, fill)
        if rect:
            self.dirty = rect.unite(self.dirty)
        return rect

    # TODO to be implemented
    # def draw_ellipse(self, brush, pos, size, color=0, fill=False):
    #     pass
