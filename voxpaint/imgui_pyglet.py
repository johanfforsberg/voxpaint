"""
Tweaked version of the imgui pyglet integration, to use pyglet's gl wrapper
instead of PyOpenGL's. Hopefully won't be needed forever.
"""

from ctypes import byref, create_string_buffer, cast, pointer, POINTER, c_char, c_void_p, c_int, c_uint

from pyglet.window import key, mouse
from pyglet import gl

import imgui


class BaseOpenGLRenderer(object):
    def __init__(self):
        imgui.create_context()
        self.io = imgui.get_io()

        self._font_texture = None

        self.io.delta_time = 1.0 / 60.0

        self._create_device_objects()
        self.refresh_font_texture()

        # todo: add option to set new_frame callback/implementation
        #self.io.render_callback = self.render

    def render(self, draw_data):
        raise NotImplementedError

    def refresh_font_texture(self):
        raise NotImplementedError

    def _create_device_objects(self):
        raise NotImplementedError

    def _invalidate_device_objects(self):
        raise NotImplementedError

    def shutdown(self):
        self._invalidate_device_objects()
        imgui.destroy_context()


def make_string_buffer(src):
    src_buffer = create_string_buffer(src)
    buf_pointer = cast(pointer(pointer(src_buffer)), POINTER(POINTER(c_char)))
    return buf_pointer


class ProgrammablePipelineRenderer(BaseOpenGLRenderer):
    """Basic OpenGL integration base class."""

    VERTEX_SHADER_SRC = b"""
    #version 330

    uniform mat4 ProjMtx;
    in vec2 Position;
    in vec2 UV;
    in vec4 Color;
    out vec2 Frag_UV;
    out vec4 Frag_Color;

    void main() {
        Frag_UV = UV;
        Frag_Color = Color;

        gl_Position = ProjMtx * vec4(Position.xy, 0, 1);
    }
    """

    FRAGMENT_SHADER_SRC = b"""
    #version 330

    uniform sampler2D Texture;
    in vec2 Frag_UV;
    in vec4 Frag_Color;
    out vec4 Out_Color;

    void main() {
        Out_Color = Frag_Color * texture(Texture, Frag_UV.st);
    }
    """

    def __init__(self):
        self._shader_handle = None
        self._vert_handle = None
        self._fragment_handle = None

        self._attrib_location_tex = None
        self._attrib_proj_mtx = None
        self._attrib_location_position = None
        self._attrib_location_uv = None
        self._attrib_location_color = None

        self._vbo_handle = None
        self._elements_handle = None
        self._vao_handle = None

        super(ProgrammablePipelineRenderer, self).__init__()

    def refresh_font_texture(self):
        # save texture state

        last_texture = gl.GLint()
        gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D, byref(last_texture))

        width, height, pixels = self.io.fonts.get_tex_data_as_rgba32()

        if self._font_texture is not None:
            gl.glDeleteTextures(1, self._font_texture)

        self._font_texture = gl.GLuint()
        gl.glGenTextures(1, byref(self._font_texture))

        gl.glBindTexture(gl.GL_TEXTURE_2D, self._font_texture)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, width, height, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixels)

        self.io.fonts.texture_id = self._font_texture
        gl.glBindTexture(gl.GL_TEXTURE_2D, cast((c_int*1)(last_texture), POINTER(c_uint)).contents)
        self.io.fonts.clear_tex_data()

    def _create_device_objects(self):
        # save state
        last_texture = gl.GLint()
        gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D, byref(last_texture))
        last_array_buffer = gl.GLint()
        gl.glGetIntegerv(gl.GL_ARRAY_BUFFER_BINDING, byref(last_array_buffer))

        last_vertex_array = gl.GLint()
        gl.glGetIntegerv(gl.GL_VERTEX_ARRAY_BINDING, byref(last_vertex_array))

        self._shader_handle = gl.glCreateProgram()
        # note: no need to store shader parts handles after linking
        vertex_shader = gl.glCreateShader(gl.GL_VERTEX_SHADER)
        fragment_shader = gl.glCreateShader(gl.GL_FRAGMENT_SHADER)

        gl.glShaderSource(vertex_shader, 1, make_string_buffer(self.VERTEX_SHADER_SRC), None)
        gl.glShaderSource(fragment_shader, 1, make_string_buffer(self.FRAGMENT_SHADER_SRC), None)
        gl.glCompileShader(vertex_shader)
        gl.glCompileShader(fragment_shader)

        gl.glAttachShader(self._shader_handle, vertex_shader)
        gl.glAttachShader(self._shader_handle, fragment_shader)

        gl.glLinkProgram(self._shader_handle)

        # note: after linking shaders can be removed
        gl.glDeleteShader(vertex_shader)
        gl.glDeleteShader(fragment_shader)

        self._attrib_location_tex = gl.glGetUniformLocation(self._shader_handle, create_string_buffer(b"Texture"))
        self._attrib_proj_mtx = gl.glGetUniformLocation(self._shader_handle, create_string_buffer(b"ProjMtx"))
        self._attrib_location_position = gl.glGetAttribLocation(self._shader_handle, create_string_buffer(b"Position"))
        self._attrib_location_uv = gl.glGetAttribLocation(self._shader_handle, create_string_buffer(b"UV"))
        self._attrib_location_color = gl.glGetAttribLocation(self._shader_handle, create_string_buffer(b"Color"))

        self._vbo_handle = gl.GLuint()
        gl.glGenBuffers(1, byref(self._vbo_handle))
        self._elements_handle = gl.GLuint()
        gl.glGenBuffers(1, byref(self._elements_handle))

        self._vao_handle = gl.GLuint()
        gl.glGenVertexArrays(1, byref(self._vao_handle))
        gl.glBindVertexArray(self._vao_handle)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_handle)

        gl.glEnableVertexAttribArray(self._attrib_location_position)
        gl.glEnableVertexAttribArray(self._attrib_location_uv)
        gl.glEnableVertexAttribArray(self._attrib_location_color)

        gl.glVertexAttribPointer(self._attrib_location_position, 2, gl.GL_FLOAT, gl.GL_FALSE, imgui.VERTEX_SIZE, c_void_p(imgui.VERTEX_BUFFER_POS_OFFSET))
        gl.glVertexAttribPointer(self._attrib_location_uv, 2, gl.GL_FLOAT, gl.GL_FALSE, imgui.VERTEX_SIZE, c_void_p(imgui.VERTEX_BUFFER_UV_OFFSET))
        gl.glVertexAttribPointer(self._attrib_location_color, 4, gl.GL_UNSIGNED_BYTE, gl.GL_TRUE, imgui.VERTEX_SIZE, c_void_p(imgui.VERTEX_BUFFER_COL_OFFSET))

        # restore state

        gl.glBindTexture(gl.GL_TEXTURE_2D, cast((c_int*1)(last_texture), POINTER(c_uint)).contents)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, cast((c_int*1)(last_array_buffer), POINTER(c_uint)).contents)
        gl.glBindVertexArray(cast((c_int*1)(last_vertex_array), POINTER(c_uint)).contents)

    def render(self, draw_data):
        # perf: local for faster access
        io = self.io

        display_width, display_height = io.display_size
        fb_width = int(display_width * io.display_fb_scale[0])
        fb_height = int(display_height * io.display_fb_scale[1])

        if fb_width == 0 or fb_height == 0:
            return

        draw_data.scale_clip_rects(*io.display_fb_scale)

        # backup GL state
        # todo: provide cleaner version of this backup-restore code
        last_program = gl.GLint()
        gl.glGetIntegerv(gl.GL_CURRENT_PROGRAM, byref(last_program))
        last_texture = gl.GLint()
        gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D, byref(last_texture))
        last_active_texture = gl.GLint()
        gl.glGetIntegerv(gl.GL_ACTIVE_TEXTURE, byref(last_active_texture))
        last_array_buffer = gl.GLint()
        gl.glGetIntegerv(gl.GL_ARRAY_BUFFER_BINDING, byref(last_array_buffer))
        last_element_array_buffer = gl.GLint()
        gl.glGetIntegerv(gl.GL_ELEMENT_ARRAY_BUFFER_BINDING, byref(last_element_array_buffer))
        last_vertex_array = gl.GLint()
        gl.glGetIntegerv(gl.GL_VERTEX_ARRAY_BINDING, byref(last_vertex_array))
        last_blend_src = gl.GLint()
        gl.glGetIntegerv(gl.GL_BLEND_SRC, byref(last_blend_src))
        last_blend_dst = gl.GLint()
        gl.glGetIntegerv(gl.GL_BLEND_DST, byref(last_blend_dst))
        last_blend_equation_rgb = gl.GLint()
        gl.glGetIntegerv(gl.GL_BLEND_EQUATION_RGB, byref(last_blend_equation_rgb))
        last_blend_equation_alpha = gl.GLint()
        gl.glGetIntegerv(gl.GL_BLEND_EQUATION_ALPHA, byref(last_blend_equation_alpha))
        last_viewport = (gl.GLint*4)()
        gl.glGetIntegerv(gl.GL_VIEWPORT, last_viewport)
        last_scissor_box = (gl.GLint*4)()
        gl.glGetIntegerv(gl.GL_SCISSOR_BOX, last_scissor_box)
        last_enable_blend = gl.GLint()
        gl.glIsEnabled(gl.GL_BLEND, byref(last_enable_blend))
        last_enable_cull_face = gl.GLint()
        gl.glIsEnabled(gl.GL_CULL_FACE, byref(last_enable_cull_face))
        last_enable_depth_test = gl.GLint()
        gl.glIsEnabled(gl.GL_DEPTH_TEST, byref(last_enable_depth_test))
        last_enable_scissor_test = gl.GLint()
        gl.glIsEnabled(gl.GL_SCISSOR_TEST, byref(last_enable_scissor_test))

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendEquation(gl.GL_FUNC_ADD)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_SCISSOR_TEST)
        gl.glActiveTexture(gl.GL_TEXTURE0)

        gl.glViewport(0, 0, int(fb_width), int(fb_height))

        ortho_projection = [
            2.0/display_width, 0.0,                   0.0, 0.0,
            0.0,               2.0/-display_height,   0.0, 0.0,
            0.0,               0.0,                  -1.0, 0.0,
            -1.0,               1.0,                   0.0, 1.0
        ]

        gl.glUseProgram(self._shader_handle)
        gl.glUniform1i(self._attrib_location_tex, 0)
        gl.glUniformMatrix4fv(self._attrib_proj_mtx, 1, gl.GL_FALSE, (gl.GLfloat * 16)(*ortho_projection))
        gl.glBindVertexArray(self._vao_handle)

        for commands in draw_data.commands_lists:
            idx_buffer_offset = 0

            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._vbo_handle)
            # todo: check this (sizes)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, commands.vtx_buffer_size * imgui.VERTEX_SIZE, c_void_p(commands.vtx_buffer_data), gl.GL_STREAM_DRAW)

            gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self._elements_handle)
            # todo: check this (sizes)
            gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, commands.idx_buffer_size * imgui.INDEX_SIZE, c_void_p(commands.idx_buffer_data), gl.GL_STREAM_DRAW)

            # todo: allow to iterate over _CmdList
            for command in commands.commands:
                gl.glBindTexture(gl.GL_TEXTURE_2D, command.texture_id)

                # todo: use named tuple
                x, y, z, w = command.clip_rect
                gl.glScissor(int(x), int(fb_height - w), int(z - x), int(w - y))

                if imgui.INDEX_SIZE == 2:
                    gltype = gl.GL_UNSIGNED_SHORT
                else:
                    gltype = gl.GL_UNSIGNED_INT

                gl.glDrawElements(gl.GL_TRIANGLES, command.elem_count, gltype, c_void_p(idx_buffer_offset))

                idx_buffer_offset += command.elem_count * imgui.INDEX_SIZE

        # restore modified GL state
        gl.glUseProgram(cast((c_int*1)(last_program), POINTER(c_uint)).contents)
        gl.glActiveTexture(cast((c_int*1)(last_active_texture), POINTER(c_uint)).contents)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cast((c_int*1)(last_texture), POINTER(c_uint)).contents)
        gl.glBindVertexArray(cast((c_int*1)(last_vertex_array), POINTER(c_uint)).contents)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, cast((c_int*1)(last_array_buffer), POINTER(c_uint)).contents)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, cast((c_int*1)(last_element_array_buffer), POINTER(c_uint)).contents)
        gl.glBlendEquationSeparate(cast((c_int*1)(last_blend_equation_rgb), POINTER(c_uint)).contents,
                                   cast((c_int*1)(last_blend_equation_alpha), POINTER(c_uint)).contents)
        gl.glBlendFunc(cast((c_int*1)(last_blend_src), POINTER(c_uint)).contents,
                       cast((c_int*1)(last_blend_dst), POINTER(c_uint)).contents)

        if last_enable_blend:
            gl.glEnable(gl.GL_BLEND)
        else:
            gl.glDisable(gl.GL_BLEND)

        if last_enable_cull_face:
            gl.glEnable(gl.GL_CULL_FACE)
        else:
            gl.glDisable(gl.GL_CULL_FACE)

        if last_enable_depth_test:
            gl.glEnable(gl.GL_DEPTH_TEST)
        else:
            gl.glDisable(gl.GL_DEPTH_TEST)

        if last_enable_scissor_test:
            gl.glEnable(gl.GL_SCISSOR_TEST)
        else:
            gl.glDisable(gl.GL_SCISSOR_TEST)

        gl.glViewport(last_viewport[0], last_viewport[1], last_viewport[2], last_viewport[3])
        gl.glScissor(last_scissor_box[0], last_scissor_box[1], last_scissor_box[2], last_scissor_box[3])

    def _invalidate_device_objects(self):
        if self._vao_handle.value > -1:
            gl.glDeleteVertexArrays(1, byref(self._vao_handle))
        if self._vbo_handle.value > -1:
            gl.glDeleteBuffers(1, byref(self._vbo_handle))
        if self._elements_handle.value > -1:
            gl.glDeleteBuffers(1, byref(self._elements_handle))
        self._vao_handle = self._vbo_handle = self._elements_handle = 0

        gl.glDeleteProgram(self._shader_handle)
        self._shader_handle = 0

        if self._font_texture.value > -1:
            gl.glDeleteTextures(1, byref(self._font_texture))
        self.io.fonts.texture_id = 0
        self._font_texture = 0


class PygletMixin(object):
    REVERSE_KEY_MAP = {
        key.TAB: imgui.KEY_TAB,
        key.LEFT: imgui.KEY_LEFT_ARROW,
        key.RIGHT: imgui.KEY_RIGHT_ARROW,
        key.UP: imgui.KEY_UP_ARROW,
        key.DOWN: imgui.KEY_DOWN_ARROW,
        key.PAGEUP: imgui.KEY_PAGE_UP,
        key.PAGEDOWN: imgui.KEY_PAGE_DOWN,
        key.HOME: imgui.KEY_HOME,
        key.END: imgui.KEY_END,
        key.DELETE: imgui.KEY_DELETE,
        key.BACKSPACE: imgui.KEY_BACKSPACE,
        key.RETURN: imgui.KEY_ENTER,
        key.ESCAPE: imgui.KEY_ESCAPE,
        key.A: imgui.KEY_A,
        key.C: imgui.KEY_C,
        key.V: imgui.KEY_V,
        key.X: imgui.KEY_X,
        key.Y: imgui.KEY_Y,
        key.Z: imgui.KEY_Z,
    }

    def _map_keys(self):
        key_map = self.io.key_map

        # note: we cannot use default mechanism of mapping keys
        #       because pyglet uses weird key translation scheme
        for value in self.REVERSE_KEY_MAP.values():
            key_map[value] = value

    def on_mouse_motion(self, x, y, dx, dy):
        self.io.mouse_pos = x, self.io.display_size.y - y

    def on_key_press(self, code, mods):
        if code in self.REVERSE_KEY_MAP:
            self.io.keys_down[self.REVERSE_KEY_MAP[code]] = True
        io = imgui.get_io()
        io.key_shift = code & key.MOD_SHIFT

    def on_key_release(self, code, mods):
        if code in self.REVERSE_KEY_MAP:
            self.io.keys_down[self.REVERSE_KEY_MAP[code]] = False
        if code & key.MOD_SHIFT:
            io = imgui.get_io()
            io.key_shift = False

    def on_text(self, text):
        io = imgui.get_io()

        for char in text:
            io.add_input_character(ord(char))

    def on_mouse_drag(self, x, y, dx, dy, button, modifiers):
        self.io.mouse_pos = x, self.io.display_size.y - y

        if button == mouse.LEFT:
            self.io.mouse_down[0] = 1

        if button == mouse.MIDDLE:
            self.io.mouse_down[1] = 1

        if button == mouse.RIGHT:
            self.io.mouse_down[2] = 1

    def on_mouse_press(self, x, y, button, modifiers):
        self.io.mouse_pos = x, self.io.display_size.y - y

        if button == mouse.LEFT:
            self.io.mouse_down[0] = 1

        if button == mouse.MIDDLE:
            self.io.mouse_down[1] = 1

        if button == mouse.RIGHT:
            self.io.mouse_down[2] = 1

    def on_mouse_release(self, x, y, button, modifiers):
        self.io.mouse_pos = x, self.io.display_size.y - y

        if button == mouse.LEFT:
            self.io.mouse_down[0] = 0

        if button == mouse.MIDDLE:
            self.io.mouse_down[1] = 0

        if button == mouse.RIGHT:
            self.io.mouse_down[2] = 0

    def on_mouse_scroll(self, x, y, mods, scroll):
        self.io.mouse_wheel = scroll

    def on_resize(self, width, height):
        self.io.display_size = width, height


class PygletRenderer(PygletMixin, ProgrammablePipelineRenderer):
    def __init__(self, window, attach_callbacks=True):
        super(PygletRenderer, self).__init__()
        self.io.display_size = window.width, window.height
        self._map_keys()

        if attach_callbacks:
            window.push_handlers(self.on_mouse_motion,
                                 self.on_key_press,
                                 self.on_key_release,
                                 self.on_text,
                                 self.on_mouse_drag,
                                 self.on_mouse_press,
                                 self.on_mouse_release,
                                 self.on_mouse_scroll,
                                 self.on_resize)
