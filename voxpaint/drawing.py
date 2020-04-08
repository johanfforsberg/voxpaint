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
    Keeps the data for a drawing.

    All potentially "destructive" operations must be done through "edits" that can be reverted.
    This is required for the undo/redo system.
    """

    def __init__(self, size: Optional[Shape]=None, data: Optional[np.ndarray]=None, palette: Palette=None,
                 path: str=None):
        if data is not None:
            self._data = data
        elif size:
            if len(size) == 2:
                shape = (*size, 1)
            elif len(size) == 3:
                shape = size
            self._data = np.zeros(shape, dtype=np.uint8)
        self.palette = palette or Palette()
        self.path = path
        self.uuid = str(uuid4())

        # "layers" don't really exist, but are just "slices" in a 3d array, depending
        # on which direction is currently viewed. We therefore need a way
        # to keep track of which ones are set as "hidden" by the user. This info is then
        # used to produce a masked version of the array, which is the data that actually
        # is used from outside. Keep in mind that the hidden layers must be kept up to date
        # if layers are added/removed/swapped or other operations are made that change
        # the index of existing layers. Annoying but not really complicated.
        self.hidden_layers_by_axis = ((), (), ())

        self.undos = []
        self.redos = []

        self.plugins = {}
        self.brushes = Selectable()

        self.last_saved_version = self.version = 0

        self.lock = RLock()
        self.dirty = None
        self.all_dirty()

        # The view keeps track of how the user is seeing the drawing.
        # TODO It should be possible to have more than one view, e.g. to have a zoomed
        # out view as well as a detail view. Currently there's no UI for that though.
        self.view = DrawingView(self)

    def all_dirty(self):
        self.dirty = self.full_slice
        
    @property
    def full_slice(self):
        return tuple(slice(0, c) for c in self.shape)
        
    @property
    def data(self):
        return self._get_masked_data(self._data.shape, self.hidden_layers_by_axis)

    @lru_cache(1)
    def _get_masked_data(self, shape, hidden_layers):
        """
        The masked data is what most operations should work on, unless they need to
        touch hidden layers (which is probably not what the user expects?)
        """
        masked_data = np.ma.masked_array(self._data, fill_value=0)
        for axis, layers in enumerate(hidden_layers):
            if layers:
                slc = tuple(slice(None)
                            if i != axis else layers
                            for i in range(3))
                masked_data[slc] = np.ma.masked
        self.all_dirty()
        return masked_data

    def _update_hidden_layers(self, axis, hidden_layers):
        hidden_layers_by_axis = list(self.hidden_layers_by_axis)
        hidden_layers_by_axis[axis] = tuple(sorted(hidden_layers))
        self.hidden_layers_by_axis = tuple(hidden_layers_by_axis)
        
    @property
    def size(self):
        return self._data.shape[:2]

    @property
    def shape(self):
        return self._data.shape
    
    @property
    def rect(self):
        return self._get_rect(self.shape)

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

    # @property
    # def layers(self):
    #     return [self.data[:, :, i] for i in range(self.data.shape[2])]

    def _perform_edit(self, edit):
        with self.lock:
            slc = edit.perform(self)
        self.dirty = slice_union(slc, self.dirty, self.shape)
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

    def move_layer(self, from_index, to_index, axis):
        edit = LayerSwapEdit(from_index, to_index, axis)
        self._perform_edit(edit)

    def _get_layer_slice(self, index, axis):
        return tuple(slice(None) if i != axis else index for i in range(3))
        
    def _really_swap_layers(self, index1, index2, axis):
        "Helper to swap layers for real. Keeps track of hidden layers, which is fiddly."
        slc1 = self._get_layer_slice(index1, axis)
        slc2 = self._get_layer_slice(index2, axis)
        data1 = self._data[slc1].copy()
        data2 = self._data[slc2].copy()
        self._data[slc1] = data2
        self._data[slc2] = data1
        
        hidden_layers = set(self.hidden_layers_by_axis[axis])
        if (index1 in hidden_layers and index2 not in hidden_layers):
            hidden_layers.remove(index1)
            hidden_layers.add(index2)
        elif (index1 not in hidden_layers and index2 in hidden_layers):
            hidden_layers.remove(index2)
            hidden_layers.add(index1)
        self._update_hidden_layers(axis, hidden_layers)
        
    def insert_layers(self, index, axis, n):
        # TODO need to be able to also add layers at the top.
        shape = list(self.shape)
        shape[axis] = n       
        edit = LayersInsertEdit.create(np.zeros(shape, dtype=np.uint8), index, axis, n)
        self._perform_edit(edit)

    def _really_insert_layers(self, data, index, axis, n):
        shape = list(self.shape)
        shape[axis] = n
        data = data.reshape(shape)
        self._data = np.insert(self._data, [index], data, axis)

        hidden_layers = sorted(self.hidden_layers_by_axis[axis])
        lower_layers = (l for l in hidden_layers if l < index)
        upper_layers = (l + n for l in hidden_layers if l >= index)
        self._update_hidden_layers(axis, (*lower_layers, *upper_layers))

    def delete_layers(self, index, axis, n):
        edit = LayersDeleteEdit.create(self, index, axis, n)
        self._perform_edit(edit)
        
    def _really_remove_layers(self, index, axis, n):
        shape = list(self.shape)
        shape[axis] = n
        self._data = np.delete(self._data, index, axis)

        hidden_layers = sorted(self.hidden_layers_by_axis[axis])
        lower_layers = (l for l in hidden_layers if l < index)
        upper_layers = (l - n for l in hidden_layers if l >= index + n)
        self._update_hidden_layers(axis, (*lower_layers, *upper_layers))
        
    def duplicate_layer(self, index, axis):
        edit = LayersInsertEdit.create(np.take(self.data, index, axis), index, axis, 1)
        self._perform_edit(edit)
        
    def undo(self):
        try:
            edit = self.undos.pop()
            self.redos.append(edit)
            with self.lock:
                slc = edit.revert(self)
            self.dirty = slice_union(slc, self.dirty, self.shape)
            self.version += 1
        except IndexError:
            pass

    def redo(self):
        try:
            edit = self.redos.pop()
            self.undos.append(edit)
            with self.lock:
                slc = edit.perform(self)
            self.dirty = slice_union(slc, self.dirty, self.shape)
            self.version += 1
        except IndexError:
            pass

    def hide_layer(self, index, axis):
        hidden_layers = set(self.hidden_layers_by_axis[axis])
        hidden_layers.add(index)
        self._update_hidden_layers(axis, hidden_layers)

    def show_layer(self, index, axis):
        hidden_layers = set(self.hidden_layers_by_axis[axis])
        hidden_layers.discard(index)
        self._update_hidden_layers(axis, hidden_layers)

    def layer_visible(self, index, axis):
        hidden_layers = set(self.hidden_layers_by_axis[axis])
        return index not in hidden_layers
        
    def toggle_layer(self, index, axis):
        if self.layer_visible(index, axis):
            self.hide_layer(index, axis)
        else:
            self.show_layer(index, axis)
        
    # def get_view(self, rotation=(0, 0, 0)):
    #     return DrawingView(self, rotation)
    
    def __hash__(self):
        return hash((id(self), self.shape))

    
