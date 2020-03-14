from pyglet import gl

from fogl.texture import Texture


class IntegerTexture(Texture):

    _type = gl.GL_RGBA8UI

    def clear(self):
        gl.glClearTexImage(self.name, 0, gl.GL_RED_INTEGER, gl.GL_UNSIGNED_BYTE, None)


class ByteIntegerTexture(IntegerTexture):

    _type = gl.GL_R8UI
