from dataclasses import dataclass
import numpy as np
import zlib

from .util import slice_union


class Edit:
    pass


@dataclass(frozen=True)
class LayerEdit(Edit):
    
    slc: tuple
    diff: bytes
    points: list
    color: int

    @classmethod
    def create(cls, drawing, slc, data, tool):
        mask = data.astype(np.bool)
        return cls(
            slc,
            zlib.compress(np.subtract(data, mask * drawing.data[slc], dtype=np.int16).tobytes()),
            [],  # tool.points,
            tool.color
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

    def perform(self, drawing):
        drawing.palette.set_colors(self.start_index, self.data)
        return None
        
    def revert(self, drawing):
        drawing.palette.set_colors(self.start_index, self.orig_data)
        return None


@dataclass(frozen=True)
class LayerSwapEdit(Edit):

    "Swap places between two layers."
    
    slc1: int
    slc2: int

    def perform(self, drawing):
        a, b = drawing.data[self.slc1].copy(), drawing.data[self.slc2].copy()
        drawing.data[self.slc1], drawing.data[self.slc2] = b, a
        return slice_union(self.slc1, self.slc2, drawing.data.shape)

    revert = perform  # This is a symmetric operation


@dataclass(frozen=True)
class LayersDeleteEdit(Edit):

    index: int
    axis: int
    n: int
    data: bytes

    @classmethod
    def create(cls, drawing, index, axis, n):
        data = np.take(drawing.data, indices=[index], axis=axis)
        return cls(
            index,
            axis,
            n,
            zlib.compress(data.tobytes()),
        )

    def perform(self, drawing):
        drawing.data = np.delete(drawing.data, self.index, self.axis)
        return tuple(slice(0, c) for c in drawing.shape) 
    
    def revert(self, drawing):
        shape = list(drawing.data.shape)
        shape[self.axis] = self.n
        data = np.frombuffer(zlib.decompress(self.data), dtype=np.uint8).reshape(shape)
        np.set_printoptions(threshold=100000)
        drawing.data = np.insert(drawing.data, [self.index], data, self.axis)
        return tuple(slice(0, c) for c in drawing.shape) 


@dataclass(frozen=True)
class LayersInsertEdit(Edit):

    index: int
    axis: int
    n: int
    data: bytes
    
    @classmethod
    def create(cls, data, index, axis, n):
        return cls(
            index,
            axis,
            n,
            zlib.compress(data.tobytes()),
        )

    perform = LayersDeleteEdit.revert
    revert = LayersDeleteEdit.perform
