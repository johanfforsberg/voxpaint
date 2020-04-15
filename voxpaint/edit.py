from dataclasses import dataclass
import numpy as np
import zlib

from .util import slice_union


class Edit:

    @classmethod
    def create(cls, drawing, *args, **kwargs):
        return cls(
            *args, 
            version=drawing.version,
            **kwargs
        )


@dataclass(frozen=True)    
class LayerEdit(Edit):
    
    slc: tuple
    diff: bytes
    points: list
    color: int
    version: int

    @classmethod
    def create(cls, drawing, slc, data, tool):
        mask = data.astype(np.bool)
        diff = np.subtract(data, mask * drawing.data[slc], dtype=np.int16)
        return cls(
            slc,
            zlib.compress(diff.tobytes()),
            [],  # tool.points,
            tool.color,
            drawing.version
        )

    def perform(self, drawing):
        slc = sx, sy, sz = self.slc
        shape = [abs(sx.stop - sx.start), abs(sy.stop - sy.start), abs(sz.stop - sz.start)]
        diff = np.frombuffer(zlib.decompress(self.diff),
                             dtype=np.int16).reshape(shape)
        drawing.data[slc] = np.add(drawing.data[slc], diff, casting="unsafe")
        return slc

    def revert(self, drawing):
        slc = sx, sy, sz = self.slc
        shape = [abs(sx.stop - sx.start), abs(sy.stop - sy.start), abs(sz.stop - sz.start)]
        diff = np.frombuffer(zlib.decompress(self.diff),
                             dtype=np.int16).reshape(shape)
        drawing.data[slc] = np.subtract(drawing.data[slc], diff, casting="unsafe")
        return slc


@dataclass(frozen=True)
class PaletteEdit(Edit):

    "A change in the color data of the palette."

    start_index: int
    orig_data: tuple
    data: tuple
    version: int

    def perform(self, drawing):
        drawing.palette.set_colors(self.start_index, self.data)
        return None
        
    def revert(self, drawing):
        drawing.palette.set_colors(self.start_index, self.orig_data)
        return None


@dataclass(frozen=True)
class LayerSwapEdit(Edit):

    "Swap places between two layers."
    
    index1: int
    index2: int
    axis: int
    version: int

    def perform(self, drawing):
        drawing._really_swap_layers(self.index1, self.index2, self.axis)
        return drawing.full_slice  # TODO not necessary to report whole drawing as dirty
        
    revert = perform  # This is a symmetric operation


@dataclass(frozen=True)
class LayersDeleteEdit(Edit):

    index: int
    axis: int
    n: int
    data: bytes
    version: int

    @classmethod
    def create(cls, drawing, index, axis, n):
        data = np.take(drawing.data, indices=[index], axis=axis)
        return cls(
            index,
            axis,
            n,
            zlib.compress(data.tobytes()),
            drawing.version
        )

    def perform(self, drawing):
        drawing._really_remove_layers(self.index, self.axis, self.n)
        return tuple(slice(0, c) for c in drawing.shape) 
    
    def revert(self, drawing):
        data = np.frombuffer(zlib.decompress(self.data), dtype=np.uint8)
        drawing._really_insert_layers(data, self.index, self.axis, self.n)
        return tuple(slice(0, c) for c in drawing.shape) 


@dataclass(frozen=True)
class LayersInsertEdit(Edit):

    index: int
    axis: int
    n: int
    data: bytes
    version: int
    
    @classmethod
    def create(cls, drawing, data, index, axis, n):
        return cls(
            index,
            axis,
            n,
            zlib.compress(data.tobytes()),
            drawing.version
        )

    perform = LayersDeleteEdit.revert
    revert = LayersDeleteEdit.perform


@dataclass(frozen=True)
class DrawingRotateEdit(Edit):

    amount: int
    axis: int
    version: int

    @classmethod
    def create(cls, drawing, amount, axis):
        return cls(
            amount,
            axis,
            drawing.version
        )
    
    def perform(self, drawing):
        drawing._really_rotate(self.amount, self.axis)

    def revert(self, drawing):
        drawing._really_rotate(-self.amount, self.axis)
        

@dataclass(frozen=True)
class DrawingFlipEdit(Edit):

    axis: int
    version: int

    @classmethod
    def create(cls, drawing, axis):
        return cls(
            axis,
            drawing.version
        )
    
    def perform(self, drawing):
        drawing._really_flip(self.axis)

    revert = perform
        
        
