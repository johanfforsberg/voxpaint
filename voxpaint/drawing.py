from functools import lru_cache
from typing import Optional, Tuple, List
import os
from threading import RLock

import numpy as np

from .edit import LayerEdit, PaletteEdit
from .ora import load_ora, save_ora
from .palette import Palette
from .rect import Rectangle
from .util import Selectable
from .view import DrawingView


Shape = Tuple[int, int, int]
        

class Drawing:

    """
    Keeps the data for a drawing. Should normally only be accessed via a DrawingView.
    """

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
        self.brushes = Selectable()

        self.last_saved_version = self.version = 0

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
    def brush(self):
        return self.brushes.current
    
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
        self.last_saved_version = self.version

    @property
    def unsaved(self):
        return self.last_saved_version < self.version

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

    
