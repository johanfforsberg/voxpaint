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
    #rotation: tuple
    points: list
    color: int

    @classmethod
    def create(cls, drawing, slc, data, tool):
        mask = data.astype(np.bool)
        # TODO seems like there should be a way to do this without having to
        # re-create the view every time, but I haven't found it yet. In any case
        # it's very cheap, but we need to store the rotation.
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
        #view = drawing.get_view(rotation=self.rotation)
        drawing.data[slc] = np.add(drawing.data[slc], diff, casting="unsafe")
        return slc

    def revert(self, drawing):
        slc = sx, sy, sz = self.slc
        shape = [abs(sx.stop - sx.start), abs(sy.stop - sy.start), abs(sz.stop - sz.start)]
        diff = np.frombuffer(zlib.decompress(self.diff),
                             dtype=np.int16).reshape(shape)
        # view = drawing.get_view(rotation=self.rotation)
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
        
    def revert(self, drawing):
        drawing.palette.set_colors(self.start_index, self.orig_data)


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

        
