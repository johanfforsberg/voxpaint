from ctypes import c_ubyte
from itertools import chain, product
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import math
from time import time

from euclid3 import Matrix4
import numpy as np
from pyglet import gl

from fogl.framebuffer import FrameBuffer
from fogl.glutil import gl_matrix
from fogl.mesh import Mesh
from fogl.shader import Program, VertexShader, FragmentShader
from fogl.texture import Texture, NormalTexture
from fogl.vertex import Vertices
from fogl.vao import VertexArrayObject
from fogl.util import enabled, disabled


VERTEX_SHADER = b"""
#version 450 core
precision lowp float;

layout (location = 0) in vec4 position;
layout (location = 1) in uint color_index;
layout (location = 2) in vec4 normal;

layout (location = 0) uniform mat4 proj_matrix;
layout (location = 3) uniform vec4[256] palette;

out VS_OUT {
  vec4 color;
  vec4 normal;
} vs_out;


void main() {
  gl_Position = proj_matrix * position;
  vs_out.color = palette[color_index];
  vs_out.normal = normal;
}
"""

FRAGMENT_SHADER = b"""
#version 450 core

layout (location = 1) uniform vec4 color = vec4(1, 1, 1, 1);

in VS_OUT {
  vec4 color;
  vec4 normal;
} fs_in;


layout (location = 0) out vec4 color_out;
layout (location = 1) out vec4 normal_out;
layout (location = 2) out vec4 position_out;


void main(void) {
  float z = gl_FragCoord.z;
  float light = 1 - 0.5 * z;
  color_out = fs_in.color * vec4(light, light, light, 1);
  //color_out = palette[fs_in.color];
  normal_out = fs_in.normal;
  position_out = gl_FragCoord;
}
"""


COPY_VERTEX_SHADER = b"""
#version 450 core


out VS_OUT {
  vec2 texcoord;
} vs_out;

void main(void) {
  const vec4 vertices[6] = vec4[6](vec4(-1, -1, 0, 1),
                                   vec4(1, 1, 0, 1),
                                   vec4(1, -1, 0, 1),

                                   vec4(1, 1, 0, 1),
                                   vec4(-1, -1, 0, 1),
                                   vec4(-1, 1, 0, 1));

  const vec2 texcoords[6] = vec2[6](vec2(0, 1),
                                    vec2(1, 0),
                                    vec2(1, 1),

                                    vec2(1, 0),
                                    vec2(0, 1),
                                    vec2(0, 0));

  gl_Position = vertices[gl_VertexID];
  vs_out.texcoord = texcoords[gl_VertexID];
}
"""

COPY_FRAGMENT_SHADER = b"""
#version 450 core

layout (binding=0) uniform sampler2D color;
layout (binding=1) uniform sampler2D normal;
layout (binding=2) uniform sampler2D position;

layout (binding=4) uniform sampler2D lightDepth;

in VS_OUT {
  vec2 texcoord;
} fs_in;

layout (location = 0) out vec4 color_out;

void main(void) {
    vec4 pos = texture(position, fs_in.texcoord);
    color_out = texture(color, fs_in.texcoord);
}
"""


class VoxelVertices(Vertices):
    _fields = [
        ('position', gl.GL_FLOAT, 4),
        ('color', gl.GL_UNSIGNED_BYTE, 1),
        ('normal', gl.GL_FLOAT, 4),
    ]    


class Plugin:

    """
    Show the current selection of the drawing as a three dimensional object.
    """

    # TODO: Keep internal rect instead of relying on drawing selection (maybe use it initially)
    # TODO: Better shading, lighting
    # TODO: Alternative rendering method, e.g. blocks
    # TODO: Highlight current layer somehow
    
    period = 0.1
    last_run = 0

    def __init__(self):
        self.program = Program(
            VertexShader(source=VERTEX_SHADER),
            FragmentShader(source=FRAGMENT_SHADER)
        )
        self._copy_program = Program(
            VertexShader(source=COPY_VERTEX_SHADER),
            FragmentShader(source=COPY_FRAGMENT_SHADER)
        )
        self._vao = VertexArrayObject()
        self.texture = None

    @lru_cache(1)
    def _get_buffer(self, size):
        render_textures = dict(
            color=Texture(size, unit=0, params={gl.GL_TEXTURE_MIN_FILTER: gl.GL_LINEAR}),
            normal=Texture(size, unit=1, params={gl.GL_TEXTURE_MIN_FILTER: gl.GL_LINEAR}),
            position=Texture(size, unit=2, params={gl.GL_TEXTURE_MIN_FILTER: gl.GL_LINEAR}),
        )
        return FrameBuffer(size, render_textures, autoclear=True)

    @lru_cache(1)
    def _get_shadow_buffer(self, size):
        render_textures = dict(
            # color=Texture(size, unit=0, params={gl.GL_TEXTURE_MIN_FILTER: gl.GL_LINEAR}),
            # normal=NormalTexture(size, unit=1, params={gl.GL_TEXTURE_MIN_FILTER: gl.GL_LINEAR}),
            # position=NormalTexture(size, unit=2, params={gl.GL_TEXTURE_MIN_FILTER: gl.GL_LINEAR}),            
        )
        return FrameBuffer(size, render_textures, autoclear=True, depth_unit=4)

    @lru_cache(1)
    def _get_final_buffer(self, size):
        render_textures = dict(
            color=Texture(size, unit=0, params={gl.GL_TEXTURE_MIN_FILTER: gl.GL_LINEAR}),
            normal=Texture(size, unit=1, params={gl.GL_TEXTURE_MIN_FILTER: gl.GL_LINEAR}),
            position=Texture(size, unit=2, params={gl.GL_TEXTURE_MIN_FILTER: gl.GL_LINEAR}),            
        )
        return FrameBuffer(size, render_textures, autoclear=True)
    
    @lru_cache(1)
    def _get_texture(self, size):
        return Texture(size)
    
    @lru_cache(256)
    def _get_float_color(self, r, g, b, a):
        return r/255, g/255, b/255, a/255

    @lru_cache(1)
    def _get_mesh(self, drawing, rect, colors):
        nz = drawing.data.nonzero()
        pixels = np.transpose(nz)
        values = drawing.data[nz]
        # TODO get rid of that "-z"?
        vertices = [((x, y, -z, 1), (v,), (0, 0, 1, 0))
                    for (x, y, z), v in zip(pixels, values)]
        # TODO It should be possible to send an ndarray directly to the GPU for
        # performance gain, but this requires support in fogl.buffer that I haven't
        # cracked yet.
        # dtype = np.dtype([('position', gl.GLfloat * 4),
        #                   ('index', gl.GLubyte * 1),
        #                   ('normal', gl.GLfloat * 4)])
        # vertices = np.array([((x, y, -z, 1), (v,), (0, 0, 1, 0))
        #                      for (x, y, z), v in zip(pixels, values)], dtype=dtype)
        if vertices:
            return Mesh(data=vertices, vertices_class=VoxelVertices)

    @lru_cache(1)
    def _get_colors(self, palette):
        colors = palette.colors
        float_colors = chain.from_iterable((r / 255, g / 255, b / 255, a / 255)
                                           for r, g, b, a in colors)
        return (gl.GLfloat*(4*256))(*float_colors)
        
    def __call__(self, voxpaint, drawing, 
                 altitude: float=2*math.pi/3, azimuth: float=0, spin: bool=False):
        if True:
            size = drawing.size
            depth = len(drawing.layers)
            colors = drawing.palette.as_tuple()

            mesh = self._get_mesh(drawing, drawing.rect, colors)
            if not mesh:
                # TODO hacky
                self.texture and self.texture[0].clear()
                return

            w, h = size
            vw = w + 8
            vh = h + h // 2
            view_size = (vw, vh)
            model_matrix = Matrix4.new_translate(-w/2, -h/2, depth/2).scale(1, 1, 1/math.sin(math.pi/3))

            far = w*2
            near = 0
            frust = Matrix4()
            frust[:] = (2/vw, 0, 0, 0,
                        0, 2/vh, 0, 0,
                        0, 0, -2/(far-near), 0,
                        0, 0, -(far+near)/(far-near), 1)
            
            offscreen_buffer = self._get_buffer(view_size)
            with offscreen_buffer, self.program, \
                    enabled(gl.GL_DEPTH_TEST), disabled(gl.GL_CULL_FACE):

                azimuth = time() if spin else azimuth
                view_matrix = (
                    Matrix4
                    .new_translate(0, 0, -h)
                    .rotatex(altitude)
                    .rotatez(azimuth)  # Rotate over time
                )
                colors = self._get_colors(drawing.palette)
                gl.glUniform4fv(3, 256, colors)
                
                gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE,
                                      gl_matrix(frust * view_matrix * model_matrix))
                gl.glViewport(0, 0, vw, vh)
                gl.glPointSize(1.0)

                mesh.draw(mode=gl.GL_POINTS)

            shadow_buffer = self._get_shadow_buffer(view_size)                
            with shadow_buffer, self.program, \
                    enabled(gl.GL_DEPTH_TEST), disabled(gl.GL_CULL_FACE):
                view_matrix = (
                    Matrix4
                    # .new_scale(2/w, 2/h, 1/max(w, h))
                    .new_translate(0, 0, -5)
                    .rotatex(math.pi)
                    .rotatez(azimuth)  # Rotate over time
                )
                gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE,
                                      gl_matrix(frust * view_matrix * model_matrix))

                gl.glViewport(0, 0, vw, vh)
                gl.glPointSize(1.0)

                mesh.draw(mode=gl.GL_POINTS)

            final_buffer = self._get_final_buffer(view_size)
            
            with self._vao, final_buffer, self._copy_program, disabled(gl.GL_CULL_FACE, gl.GL_DEPTH_TEST):
                with offscreen_buffer["color"], offscreen_buffer["normal"], offscreen_buffer["position"], shadow_buffer["depth"]:
                    gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
                
            # TODO must be careful here so that the texture is always valid
            # (since imgui may read it at any time) Find a way to ensure this.
            texture = self._get_texture(view_size)
            gl.glCopyImageSubData(final_buffer["color"].name, gl.GL_TEXTURE_2D, 0, 0, 0, 0,
                                  texture.name, gl.GL_TEXTURE_2D, 0, 0, 0, 0,
                                  vw, vh, 1)
            self.texture = texture, view_size
