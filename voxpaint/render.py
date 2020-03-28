from functools import lru_cache
from itertools import chain

from pyglet import gl

from fogl.framebuffer import FrameBuffer
from fogl.shader import Program, VertexShader, FragmentShader
from fogl.texture import Texture, ByteTexture3D
from fogl.vao import VertexArrayObject

from .texture import IntegerTexture


EMPTY_COLOR = (gl.GLfloat * 4)(0, 0, 0, 0)


def render_view(window):

    """ Render the current view to a texture. """

    drawing = window.drawing
    view = window.view
    data = view.data
    w, h, d = view.shape
    size = w, h
    offscreen_buffer = _get_offscreen_buffer(size)
    colors = _get_colors(drawing.palette.colors)
    
    # Update the overlay with the current stroke
    overlay = view.overlay
    overlay_texture = _get_overlay_texture(size)
    if overlay.dirty and overlay.lock.acquire(timeout=0.01):
        rect = overlay.dirty
        x0, y0, x1, y1 = rect.box()
        overlay_data = overlay.data[x0:x1, y0:y1].tobytes("F")
        gl.glTextureSubImage2D(overlay_texture.name, 0, *rect.position, *rect.size,
                               gl.GL_RGBA_INTEGER, gl.GL_UNSIGNED_BYTE, overlay_data)
        overlay.dirty = None
        overlay.lock.release()

    # Update the image texture
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)  # Needed for writing 8bit data
    drawing_texture = _get_3d_texture(view.shape)        
    for i in range(d):

        if not view.layer_visible(i):
            continue

        dirty = view.dirty[i]
        if dirty and drawing.lock.acquire(timeout=0.01):
            print("hej")
            layer = data[:, :, i]
            layer_data = layer.tobytes("F")  # TODO maybe there's a better way?
            gl.glTextureSubImage3D(drawing_texture.name, 0,
                                   0, 0, i, w, h, 1,  # TODO use dirty rect
                                   gl.GL_RED_INTEGER, gl.GL_UNSIGNED_BYTE,
                                   layer_data)
            view.dirty[i] = None
    gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)

    # Render everything to the offscreen buffer
    cursor_pos = view.layer_index

    vao = _get_vao()
    draw_program = _get_program()
    empty_texture = _get_empty_texture(size)
    
    with vao, offscreen_buffer:

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glClearBufferfv(gl.GL_COLOR, 0, EMPTY_COLOR)
        gl.glViewport(0, 0, w, h)

        with draw_program, drawing_texture:

            gl.glUniform4fv(4, 256, colors)

            # Draw the layers below the current one
            if cursor_pos > 0:
                with empty_texture:
                    gl.glUniform1f(1, 1)
                    gl.glUniform2i(2, 0, cursor_pos)
                    gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)

            # Draw the current layer + overlay
            with overlay_texture:
                gl.glUniform1f(1, 1)
                gl.glUniform2i(2, cursor_pos, cursor_pos + 1)
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
                
            # Draw the layers on top
            if cursor_pos < d - 1:
                with empty_texture:
                    gl.glUniform1f(1, 1)
                    gl.glUniform2i(2, cursor_pos + 1, d)
                    gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)

    return offscreen_buffer


# Helper functions to cache frequently used stuff.

@lru_cache(1)
def _get_vao():
    return VertexArrayObject()


@lru_cache(1)
def _get_program():
    return Program(VertexShader("glsl/palette_vert.glsl"),
                   FragmentShader("glsl/palette_frag.glsl"))


@lru_cache(1)
def _get_offscreen_buffer(size):
    return FrameBuffer(size, textures=dict(color=Texture(size, unit=0)))


@lru_cache(1)
def _get_3d_texture(size):
    "We'll store the entire image in a texture array."
    texture = ByteTexture3D(size=size)
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



