from dataclasses import dataclass
import numpy as np
import zlib


@dataclass(frozen=True)
class LayerEdit:
    
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
