from functools import lru_cache
from itertools import chain

import numpy as np
from pyglet import gl

from fogl.framebuffer import FrameBuffer
from fogl.shader import Program, VertexShader, FragmentShader
from fogl.texture import Texture, ByteTexture3D
from fogl.vao import VertexArrayObject

from .constants import Rx90, Ry90, Rz90
from .texture import IntegerTexture


EMPTY_COLOR = (gl.GLfloat * 4)(0, 0, 0, 0)


def render_view(window):

    """ Render the current view to a texture. """

    drawing = window.drawing
    view = window.view

    changed = False
    
    # Update the overlay with the current stroke
    overlay = view.overlay
    w, h, d = view.shape
    size = w, h    
    overlay_texture = _get_overlay_texture(size)
    if overlay.dirty and overlay.lock.acquire(timeout=0.01):
        rect = overlay.dirty
        x0, y0, x1, y1 = rect.box()
        overlay_data = overlay.data[x0:x1, y0:y1].tobytes("F")
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)  # Needed for writing 8bit data                
        gl.glTextureSubImage2D(overlay_texture.name, 0, *rect.position, *rect.size,
                               gl.GL_RGBA_INTEGER, gl.GL_UNSIGNED_BYTE, overlay_data)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
        overlay.dirty = None
        overlay.lock.release()
        changed = True

    # Update the image texture
    data = drawing.data
    drawing_texture = _get_3d_texture(data.shape)
    if drawing.dirty:
        with drawing.lock:
            update_data = data[drawing.dirty].tobytes(order="F")
            sx, sy, sz = drawing.dirty
            drawing.dirty = None
        sw = sx.stop - sx.start
        sh = sy.stop - sy.start
        sd = sz.stop - sz.start
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)  # Needed for writing 8bit data        
        gl.glTextureSubImage3D(drawing_texture.name, 0,
                               sx.start, sy.start, sz.start, sw, sh, sd,
                               gl.GL_RED_INTEGER, gl.GL_UNSIGNED_BYTE,
                               update_data)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)
        changed = True

    # Render everything to the offscreen buffer

    # TODO we actually should not have to redraw the offscreen_buffer unless something has changed
    # (e.g. drawing, overlay, palette or cursor)

    offscreen_buffer = _get_offscreen_buffer(size)
    colors = _get_colors(drawing.palette.colors)

    vao = _get_vao()
    draw_program = _get_program()
    empty_texture = _get_empty_texture(size)    

    cursor_pos = d - view.layer_index - 1  # TODO why?

    other_layer_alpha = 0.3 if view.show_only_current_layer or view.layer_being_switched else 1.0

    T = _get_transform(view.rotation)
    
    with vao, offscreen_buffer:

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glViewport(0, 0, w, h)
        gl.glClearBufferfv(gl.GL_COLOR, 0, EMPTY_COLOR)

        with draw_program, drawing_texture:

            gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE, (gl.GLfloat*16)(*T))
            gl.glUniform3f(1, *view.direction)
            gl.glUniform4fv(5, 256, colors)

            # Draw the layers below the current one
            if cursor_pos < d - 1:            
                with empty_texture:
                    gl.glUniform1f(2, other_layer_alpha)
                    gl.glUniform2i(3, cursor_pos+1, d)
                    gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
                
            # Draw the current layer + overlay
            with overlay_texture:
                gl.glUniform1f(2, 1)
                gl.glUniform2i(3, cursor_pos, cursor_pos + 1)
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
                
            # Draw the layers on top
            if cursor_pos > 0:
                with empty_texture:
                    gl.glUniform1f(2, other_layer_alpha)
                    gl.glUniform2i(3, 0, cursor_pos)
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


# TODO this stuff is duplicated (almost) in view.py

def make_translation(x, y, z):
    return np.matrix([[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]])
 

@lru_cache(1)
def _get_transform(rotation):
    T1 = make_translation(-1 / 2, -1 / 2, -1 / 2)
    T2 = make_translation(1 / 2, 1 / 2, 1 / 2)
    R = np.matrix(np.eye(4))
    rx, ry, rz = rotation
    for _ in range(rz):
        R *= Rz90        
    for _ in range(rx):
        R *= Rx90
    for _ in range(ry):
        R *= Ry90    
    T = T2 * R * T1
    return np.asarray(T.flatten("F"))[0]
    

