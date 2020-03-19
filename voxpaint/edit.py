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
    orig_data: bytes
    data: bytes
    points: list
    color: int

    @classmethod
    def create(cls, index, slc, rotation, layer, data, tool):
        return cls(
            index,
            slc,
            rotation,
            zlib.compress(layer[slc].tobytes()),
            zlib.compress(data.tobytes()),
            [],  # tool.points,
            tool.color
        )

    def perform(self, drawing):
        slc = sx, sy = self.slc
        shape = [abs(sx.stop - sx.start), abs(sy.stop - sy.start)]
        data = np.frombuffer(zlib.decompress(self.data),
                             dtype=np.uint32).reshape(shape)
        view = drawing.get_view(rotation=self.rotation)
        layer = view.layer(self.index)
        np.copyto(layer[slc], data, where=data > 255)

    def revert(self, drawing):
        slc = sx, sy = self.slc
        shape = [abs(sx.stop - sx.start), abs(sy.stop - sy.start)]
        data = np.frombuffer(zlib.decompress(self.orig_data),
                             dtype=np.uint8).reshape(shape)
        view = drawing.get_view(rotation=self.rotation)
        layer = view.layer(self.index)
        np.copyto(layer[slc], data)


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


