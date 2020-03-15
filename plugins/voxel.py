from itertools import chain, product
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
import math
from time import time

from pyglet import gl
from euclid3 import Matrix4

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

layout (location = 0) in vec4 position;
layout (location = 1) in vec4 color;
layout (location = 2) in vec4 normal;

layout (location = 0) uniform mat4 proj_matrix;

out VS_OUT {
  vec4 color;
  vec4 normal;
} vs_out;


void main() {
  gl_Position = proj_matrix * position;
  vs_out.color = color;
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
                                   vec4(1, -1, 0, 1),
                                   vec4(1, 1, 0, 1),

                                   vec4(-1, -1, 0, 1),
                                   vec4(1, 1, 0, 1),
                                   vec4(-1, 1, 0, 1));

  const vec2 texcoords[6] = vec2[6](vec2(0, 0),
                                    vec2(1, 0),
                                    vec2(1, 1),

                                    vec2(0, 0),
                                    vec2(1, 1),
                                    vec2(0, 1));

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
        ('color', gl.GL_FLOAT, 4),
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

    # @lru_cache(100)
    def _get_layer_vertices(self, layer, rect, colors, z):

        # if not layer.visible:
        #     return []
        #subimage = layer.get_subimage(rect)
        subdata = layer[rect.as_slice()]
        w, h = rect.size
        # TODO "w - x" is there to unmirror everything, figure out why it's needed.
        vertices = [((x, y, -z, 1),
                     self._get_float_color(*colors[subdata[x, y]]),
                     (0, 0, 1, 0))
                    for x, y in product(range(w), range(h))
                    if subdata[x, y] > 0]
        return vertices

    @lru_cache(1)
    def _get_mesh(self, drawing, rect, colors):
        vertices = list(chain.from_iterable(self._get_layer_vertices(layer, rect, colors, i)
                                            for i, layer in enumerate(drawing.layers)
                                            if True))
        if vertices:
            return Mesh(data=vertices, vertices_class=VoxelVertices)
        
    def __call__(self, voxpaint, drawing, 
                 altitude: float=-2*math.pi/3, azimuth: float=0, spin: bool=False):
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
            model_matrix = Matrix4.new_translate(-w/2, -h/2, depth/2).scale(1, 1, 1/math.sin(math.pi/3))

            far = w*2
            near = 0
            frust = Matrix4()
            frust[:] = (2/w, 0, 0, 0,
                        0, 2/h, 0, 0,
                        0, 0, -2/(far-near), 0,
                        0, 0, -(far+near)/(far-near), 1)
            
            offscreen_buffer = self._get_buffer(size)
            with offscreen_buffer, self.program, \
                    enabled(gl.GL_DEPTH_TEST), disabled(gl.GL_CULL_FACE):

                azimuth = time() if spin else azimuth
                view_matrix = (
                    Matrix4
                    # .new_scale(2/w, 2/h, 1/max(w, h))
                    .new_translate(0, 0, -w)
                    .rotatex(altitude)
                    .rotatez(azimuth)  # Rotate over time
                )
                
                gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE,
                                      gl_matrix(frust * view_matrix * model_matrix))

                gl.glViewport(0, 0, *size)
                gl.glPointSize(1.0)

                mesh.draw(mode=gl.GL_POINTS)

            shadow_buffer = self._get_shadow_buffer(size)                
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

                gl.glViewport(0, 0, *size)
                gl.glPointSize(1.0)

                mesh.draw(mode=gl.GL_POINTS)

            final_buffer = self._get_final_buffer(size)
            
            with self._vao, final_buffer, self._copy_program, disabled(gl.GL_CULL_FACE, gl.GL_DEPTH_TEST):
                with offscreen_buffer["color"], offscreen_buffer["normal"], offscreen_buffer["position"], shadow_buffer["depth"]:
                    gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
                
            # TODO must be careful here so that the texture is always valid
            # (since imgui may read it at any time) Find a way to ensure this.
            texture = self._get_texture(size)
            gl.glCopyImageSubData(final_buffer["color"].name, gl.GL_TEXTURE_2D, 0, 0, 0, 0,
                                  texture.name, gl.GL_TEXTURE_2D, 0, 0, 0, 0,
                                  w, h, 1)
            self.texture = texture, size
