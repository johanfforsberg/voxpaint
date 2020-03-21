from functools import lru_cache
from typing import Optional, Tuple, List
import math
import os
from threading import RLock

from euclid3 import Vector3
import numpy as np

from .brush import ImageBrush
from .draw import blit, draw_line, draw_rectangle
from .edit import LayerEdit, PaletteEdit
from .ora import load_ora, save_ora
from .palette import Palette
from .rect import Rectangle
from .util import AutoResetting


Shape = Tuple[int, ...]
        

class Drawing:

    def __init__(self, size:Optional[Shape]=None, data:Optional[np.ndarray]=None, palette:Palette=None,
                 path=None):
        if data is not None:
            self.data = data
        elif size:
            if len(size) == 2:
                shape = (*size, 1)
            elif len(size) == 3:
                shape = size
            self.data = np.zeros(shape, dtype=np.uint8)
        self.palette = palette or Palette()
        self.path = path
        self.filename = os.path.basename(path) if path else "[Unnamed]"

        self.lock = RLock()

        self.undos = []
        self.redos = []

        self.plugins = {}

        self.version = 0

    @property
    def size(self):
        return self.data.shape[:2]

    @property
    def shape(self):
        return self.data.shape
    
    @property
    def rect(self):
        return self._get_rect(self.data.shape)

    @lru_cache(1)
    def _get_rect(self, shape):
        return Rectangle((0, 0), shape[:2])

    @classmethod
    def from_ora(cls, path):
        data, info, _ = load_ora(path)
        return cls(data=data, palette=Palette(info["palette"]), path=path)

    def to_ora(self, path):
        view = self.get_view()
        layers = list(view.layers)
        save_ora(self.size, layers, self.palette, path)

    def save(self, path=None):
        self.path = path if path is not None else self.path
        assert self.path, "Can't save drawing; no path set."
        _, ext = os.path.splitext(self.path)
        if ext == ".ora":
            self.to_ora(self.path)
        else:
            raise ValueError(f"Can't save drawing; unknown format: {ext}")

    @property
    def layers(self):
        return [self.data[:, :, i] for i in range(self.data.shape[2])]
        
    def modify(self, index, slc, data, rotation, tool):
        # TODO This seems a little over complicated; seems like it
        # should be possible to find the slice in the original data to
        # use.
        view = DrawingView(self, rotation=rotation)
        layer = view.layer(index)
        edit = LayerEdit.create(index, slc, rotation, layer, data, tool)
        self.undos.append(edit)
        np.copyto(layer[slc], data, where=data > 255)
        self.redos.clear()
        self.version += 1

    def change_colors(self, start_i, *colors):
        orig_colors = self.palette._colors[start_i:start_i+len(colors)]
        edit = PaletteEdit(start_i, orig_colors, colors)
        self.undos.append(edit)
        edit.perform(self)
        self.version += 1
        
    def undo(self):
        try:
            edit = self.undos.pop()
            self.redos.append(edit)
            edit.revert(self)
            self.version += 1
        except IndexError:
            pass

    def redo(self):
        try:
            edit = self.redos.pop()
            self.undos.append(edit)
            edit.perform(self)
            self.version += 1
        except IndexError:
            pass

    def get_view(self, rotation=(0, 0, 0)):
        return DrawingView(self, rotation)

    def __hash__(self):
        return hash((id(self), self.data.shape))

    
class DrawingView:

    layer_being_switched = AutoResetting(False)
    
    def __init__(self, drawing, rotation=(0, 0, 0)):
        self.drawing = drawing
        self.rotation = rotation
        self.cursor = (0, 0, 0)
        self.brushes = []
        
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

    def layer_visible(self, index):
        if index == self.layer_index:
            return True
        return not self.show_only_current_layer and not self.layer_being_switched
        
    @property
    def data(self):
        return self._get_data(self.rotation)

    @lru_cache(1)
    def _get_data(self, rotation):
        " Return a ndarray view on the drawing data, rotated properly. "
        data = self.drawing.data
        rx, ry, rz = rotation
        # TODO this seems correct for the limited rotating we currently do...
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
    def layers(self):
        d = self.shape[2]
        return (self.layer(i) for i in range(d))
                    
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

    def move_layer(self, d):
        index = self.layer_index
        other_index = index + d
        if not 0 <= other_index < self.shape[2]:
            return
        current_layer = self.layer()
        above_layer = self.layer(index + d).copy()
        self.data[:, :, index + d] = current_layer
        self.data[:, :, index] = above_layer
        deltas = [d * a for a in self.direction]
        self.move_cursor(*deltas)
        self.drawing.version += 1

    def make_brush(self, rect=None, clear=False):
        if rect:
            print(rect)
            data = self.layer()[rect.as_slice()].copy()
        else:
            data = self.layer().copy()
        brush = ImageBrush(data=data)
        self.brushes.append(brush)

        
class Overlay:

    def __init__(self, size):
        self.size = size
        self.data = np.zeros(size, dtype=np.uint32)
        self.lock = RLock()
        self.rect = Rectangle((0, 0), size)
        
        self.dirty = None

    def clear_all(self):
        self.clear(self.rect)
        
    def clear(self, rect):
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

    def blit(self, data, p):
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
        # dx = dy = 0
        data = brush.get_draw_data(color)
        with self.lock:
            rect = draw_rectangle(self.data, data, (x-dx, y-dy), size, color + 2**24, fill)
        if rect:
            self.dirty = rect.unite(self.dirty)
        return rect
    
    # def draw_ellipse(self, brush, pos, size, color=0, fill=False):
    #     x, y = pos
    #     dx, dy = brush.center
    #     data = brush.get_draw_data(color)
    #     with self.lock:
    #         rect = draw_rectangle(self.data, data, (x-dx, y-dy), size, color + 2**24, fill)
    #     self.dirty = rect.unite(self.dirty)
    #     return rect
    
