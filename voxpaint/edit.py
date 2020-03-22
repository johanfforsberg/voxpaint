from dataclasses import dataclass
import numpy as np
import zlib


class Edit:
    pass


@dataclass(frozen=True)
class LayerEdit(Edit):
    
    index: int
    slc: tuple
    rotation: tuple
    diff: bytes
    points: list
    color: int

    @classmethod
    def create(cls, index, slc, rotation, layer, data, tool):
        mask = data.astype(np.bool)
        return cls(
            index,
            slc,
            rotation,
            zlib.compress(np.subtract(data, mask * layer[slc], dtype=np.int16).tobytes()),
            [],  # tool.points,
            tool.color
        )

    def perform(self, drawing):
        slc = sx, sy = self.slc
        shape = [abs(sx.stop - sx.start), abs(sy.stop - sy.start)]
        diff = np.frombuffer(zlib.decompress(self.diff),
                             dtype=np.int16).reshape(shape)
        view = drawing.get_view(rotation=self.rotation)
        layer = view.layer(self.index)
        layer[slc] = np.add(layer[slc], diff, casting="unsafe")

    def revert(self, drawing):
        slc = sx, sy = self.slc
        shape = [abs(sx.stop - sx.start), abs(sy.stop - sy.start)]
        diff = np.frombuffer(zlib.decompress(self.diff),
                             dtype=np.int16).reshape(shape)
        view = drawing.get_view(rotation=self.rotation)
        layer = view.layer(self.index)
        layer[slc] = np.subtract(layer[slc], diff, casting="unsafe")


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


