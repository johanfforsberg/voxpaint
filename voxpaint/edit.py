from dataclasses import dataclass
import numpy as np
import zlib


class Edit:
    pass


@dataclass(frozen=True)
class LayerEdit(Edit):
    
    slc: tuple
    diff: bytes
    rotation: tuple
    points: list
    color: int

    @classmethod
    def create(cls, drawing, slc, data, rotation, tool):
        mask = data.astype(np.bool)
        view = drawing.get_view(rotation)
        # TODO seems like there should be a way to do this without having to
        # re-create the view every time, but I haven't found it yet. In any case
        # it's very cheap, but we need to store the rotation.
        return cls(
            slc,
            zlib.compress(np.subtract(data, mask * view.data[slc], dtype=np.int16).tobytes()),
            rotation,
            [],  # tool.points,
            tool.color
        )

    def perform(self, drawing):
        slc = sx, sy, sz = self.slc
        shape = [abs(sx.stop - sx.start), abs(sy.stop - sy.start), abs(sz.stop - sz.start)]
        diff = np.frombuffer(zlib.decompress(self.diff),
                             dtype=np.int16).reshape(shape)
        view = drawing.get_view(rotation=self.rotation)
        view.data[slc] = np.add(view.data[slc], diff, casting="unsafe")

    def revert(self, drawing):
        slc = sx, sy, sz = self.slc
        shape = [abs(sx.stop - sx.start), abs(sy.stop - sy.start), abs(sz.stop - sz.start)]
        diff = np.frombuffer(zlib.decompress(self.diff),
                             dtype=np.int16).reshape(shape)
        view = drawing.get_view(rotation=self.rotation)
        view.data[slc] = np.subtract(view.data[slc], diff, casting="unsafe")


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


