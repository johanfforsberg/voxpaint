from functools import lru_cache
from itertools import chain

from pyglet import gl

from fogl.framebuffer import FrameBuffer
from fogl.shader import Program, VertexShader, FragmentShader
from fogl.texture import Texture, ByteTexture, ImageTexture
from fogl.vao import VertexArrayObject

from .texture import IntegerTexture, ByteIntegerTexture


draw_program = Program(VertexShader("glsl/palette_vert.glsl"),
                       FragmentShader("glsl/palette_frag.glsl"))

vao = VertexArrayObject()


EMPTY_COLOR = (gl.GLfloat * 4)(0, 0, 0, 0)


def render_view(window):

    drawing = window.drawing
    view = window.view
    data = view.data
    w, h, d = view.shape
    size = w, h
    ob = _get_offscreen_buffer(size)
    colors = _get_colors(drawing.palette.colors)
    
    gl.glClearBufferfv(gl.GL_COLOR, 0, (gl.GLfloat * 4)(0.25, 0.25, 0.25, 1))

    with vao, ob, draw_program:
        gl.glViewport(0, 0, w, h)

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glClearBufferfv(gl.GL_COLOR, 0, EMPTY_COLOR)

        cursor_pos = view.layer_index
        overlay = view.overlay
        overlay_texture = _get_overlay_texture(size)

        if overlay.dirty and overlay.lock.acquire(timeout=0.01):
            rect = overlay.dirty
            x0, y0, x1, y1 = rect.box()
            overlay_data = overlay.data[x0:x1, y0:y1].tobytes("F")
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
            gl.glTextureSubImage2D(overlay_texture.name, 0, *rect.position, *rect.size,
                                   gl.GL_RGBA_INTEGER, gl.GL_UNSIGNED_BYTE, overlay_data)
            overlay.dirty = None
            overlay.lock.release()

        # Set current palette
        gl.glUniform4fv(2, 256, colors)

        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)  # Needed for reading 8bit data

        for i in range(d):
            # TODO This is pretty slow, since we draw every layer every frame.
            # A better version would be to keep two extra fbs, one for the layers
            # below and one above, and render all non-current layers to those.
            # As long as no other layers are modified the fbs can be re-used.

            if not view.layer_visible(i):
                continue

            tex = _get_layer_texture(i, size)
            dirty = view.dirty[i]
            if dirty and drawing.lock.acquire(timeout=0.01):
                layer = data[:, :, i]
                layer_data = layer.tobytes("F")  # TODO maybe there's a better way?
                gl.glTextureSubImage2D(tex.name, 0, 0, 0, w, h,
                                       gl.GL_RED_INTEGER, gl.GL_UNSIGNED_BYTE,
                                       layer_data)
                view.dirty[i] = None
            with tex:
                if i == cursor_pos:
                    second_texture = overlay_texture
                else:
                    second_texture = _get_empty_texture(size)
                with second_texture:
                    gl.glUniform1f(1, 1)
                    gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)

        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)

    return ob


@lru_cache(1)
def _get_offscreen_buffer(size):
    return FrameBuffer(size, textures=dict(color=Texture(size, unit=0)))


@lru_cache(128)
def _get_layer_texture(i, size):
    texture = ByteTexture(size=size)
    texture.clear()
    return texture


@lru_cache(1)
def _get_overlay_texture(size):
    texture = IntegerTexture(size=size, unit=1)
    texture.clear()
    return texture


@lru_cache(1)
def _get_empty_texture(size):
    texture = IntegerTexture(size, unit=1)
    texture.clear()
    return texture


@lru_cache(1)
def _get_colors(colors):
    float_colors = chain.from_iterable((r / 255, g / 255, b / 255, a / 255)
                                       for r, g, b, a in colors)
    return (gl.GLfloat*(4*256))(*float_colors)



