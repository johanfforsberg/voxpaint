from functools import lru_cache
from typing import Optional, Tuple, List
import os
from threading import RLock
from uuid import uuid4

import numpy as np
import png

from .edit import LayerEdit, PaletteEdit, LayerSwapEdit, LayersDeleteEdit, LayersInsertEdit
from .ora import load_ora, save_ora
from .palette import Palette
from .rect import Rectangle
from .util import Selectable, slice_union
from .view import DrawingView


Shape = Tuple[int, int, int]
        

class Drawing:

    """
    Keeps the data for a drawing. Should normally only be accessed via a DrawingView.
    """

    def __init__(self, size: Optional[Shape]=None, data: Optional[np.ndarray]=None, palette: Palette=None,
                 path: str=None):
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
        self.uuid = str(uuid4())

        self.lock = RLock()

        self.undos = []
        self.redos = []

        self.plugins = {}
        self.brushes = Selectable()

        self.last_saved_version = self.version = 0

        self.dirty = None
        self.all_dirty()
        self.view = DrawingView(self)

    def all_dirty(self):
        self.dirty = tuple(slice(0, c) for c in self.shape)        
        
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

    @property
    def filename(self):
        return self._get_filename(self.path)

    @lru_cache(1)
    def _get_filename(self, path):
        return os.path.basename(path) if path else "[Unnamed]"

    @property
    def brush(self):
        return self.brushes.current

    @classmethod
    def from_png(cls, path):
        reader = png.Reader(filename=path)
        w, h, image_data, info = reader.read()
        if "palette" not in info:
            raise NotImplementedError("Can't load non palette based PNG images.")
        data = np.vstack(list(map(np.uint8, image_data))).T
        palette = Palette(info["palette"])
        return cls(data=np.dstack([data]), palette=palette, path=path)
    
    @classmethod
    def from_ora(cls, path):
        data, info, _ = load_ora(path)
        return cls(data=data, palette=Palette(info["palette"]), path=path)
    
    def to_ora(self, path):
        view = self.get_view()
        layers = list(view.layers)
        save_ora(self.size, layers, self.palette, path)

    def save(self, path=None, auto=False):
        "Save the drawing to a file, in the appropriate format inferred from the filename."
        path = path or self.path
        assert path, "Can't save drawing; no path given."
        _, ext = os.path.splitext(path)
        if ext == ".ora":
            self.to_ora(path)
        else:
            raise ValueError(f"Can't save drawing; unknown format: {ext}")
        if not auto:
            self.last_saved_version = self.version
            self.path = path

    @property
    def unsaved(self):
        return self.last_saved_version < self.version

    @property
    def layers(self):
        return [self.data[:, :, i] for i in range(self.data.shape[2])]

    def _perform_edit(self, edit):
        with self.lock:
            slc = edit.perform(self)
        self.dirty = slice_union(slc, self.dirty, self.data.shape)
        self.version += 1
        self.undos.append(edit)
        self.redos.clear()        
    
    def modify(self, slc, data, tool):
        edit = LayerEdit.create(self, slc, data, tool)
        self._perform_edit(edit)

    def change_colors(self, start_i, *colors):
        orig_colors = self.palette._colors[start_i:start_i+len(colors)]
        edit = PaletteEdit(start_i, orig_colors, colors)
        self._perform_edit(edit)

    def move_layer(self, from_slice, to_slice):
        edit = LayerSwapEdit(from_slice, to_slice)
        self._perform_edit(edit)
        
    def delete_layers(self, index, axis, n):
        edit = LayersDeleteEdit.create(self, index, axis, n)
        self._perform_edit(edit)

    def insert_layers(self, index, axis, n):
        shape = list(self.shape)
        shape[axis] = 1
        edit = LayersInsertEdit.create(np.zeros(shape, dtype=np.uint8), index, axis, n)
        self._perform_edit(edit)

    def duplicate_layer(self, index, axis):
        edit = LayersInsertEdit.create(np.take(self.data, index, axis), index, axis, 1)
        self._perform_edit(edit)
        
    def undo(self):
        try:
            edit = self.undos.pop()
            self.redos.append(edit)
            with self.lock:
                slc = edit.revert(self)
            self.dirty = slice_union(slc, self.dirty, self.data.shape)
            self.version += 1
        except IndexError:
            pass

    def redo(self):
        try:
            edit = self.redos.pop()
            self.undos.append(edit)
            with self.lock:
                slc = edit.perform(self)
            self.dirty = slice_union(slc, self.dirty, self.data.shape)
            self.version += 1
        except IndexError:
            pass

    def get_view(self, rotation=(0, 0, 0)):
        return DrawingView(self, rotation)
    
    def __hash__(self):
        return hash((id(self), self.data.shape))

    
