from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from itertools import chain
from queue import Queue

import pyximport
pyximport.install(language_level=3)  # Setup cython to autocompile pyx modules

import imgui
import numpy as np
import pyglet
from pyglet import gl
from pyglet.window import key

from fogl.framebuffer import FrameBuffer
from fogl.shader import Program, VertexShader, FragmentShader
from fogl.texture import Texture, ByteTexture, ImageTexture
from fogl.util import load_png
from fogl.vao import VertexArrayObject
from fogl.vertex import SimpleVertices

from .brush import Brush
from .constants import ToolName
from .drawing import Drawing, DrawingView
from .draw import draw_line
from .imgui_pyglet import PygletRenderer
from .palette import Palette
from .plugin import init_plugins, render_plugins_ui
from .rect import Rectangle
from .stroke import make_stroke
from .texture import IntegerTexture, ByteIntegerTexture
from .tool import (PencilTool, PointsTool, SprayTool,
                   LineTool, RectangleTool, EllipseTool,
                   SelectionTool, PickerTool, FillTool)
from . import ui
from .util import make_view_matrix, try_except_log, Selectable, Selectable2, no_imgui_events


vao = VertexArrayObject()


draw_program = Program(VertexShader("glsl/palette_vert.glsl"),
                       FragmentShader("glsl/palette_frag.glsl"))

copy_program = Program(VertexShader("glsl/copy_vert.glsl"),
                       FragmentShader("glsl/copy_frag.glsl"))

line_program = Program(VertexShader("glsl/triangle_vert.glsl"),
                       FragmentShader("glsl/triangle_frag.glsl"))


EMPTY_COLOR = (gl.GLfloat * 4)(0, 0, 0, 0)


MIN_ZOOM = -2
MAX_ZOOM = 5


class VoxpaintWindow(pyglet.window.Window):

    def __init__(self, *args, path=None, **kwargs):
        
        super().__init__(*args, **kwargs, resizable=True, vsync=False)

        if path:
            self.drawing = Drawing.from_ora(path)
        else:
            # self.drawing = Drawing((640, 480, 10), palette=Palette())
            self.drawing = Drawing((128, 128, 128), palette=Palette())
        self.view = DrawingView(self.drawing)

        self.vao = VertexArrayObject()
        self.offset = (0, 0)
        self.zoom = 2

        self.keys = key.KeyStateHandler()
        self.push_handlers(self.keys)

        self.border_vao = VertexArrayObject(vertices_class=SimpleVertices)
        self.border_vertices = self.border_vao.create_vertices(
            [((0, 0, 0),),
             ((0, 0, 0),),
             ((0, 0, 0),),
             ((0, 0, 0),)])

        self.tools = Selectable2({
            tool.tool: tool
            for tool in 
            [
                PencilTool, PointsTool, SprayTool,
                LineTool, RectangleTool,
                # EllipseTool,
                FillTool,
                # SelectionTool,
                PickerTool
            ]
        })
        self._brush = Brush((1, 1))
        self.stroke = None

        self.executor = ThreadPoolExecutor(max_workers=1)
        self.mouse_event_queue = None

        self.imgui_renderer = PygletRenderer(self)
        io = imgui.get_io()
        self._font = io.fonts.add_font_from_file_ttf(
            "ttf/Topaznew.ttf", 16, io.fonts.get_glyph_ranges_latin()
        )
        self.imgui_renderer.refresh_font_texture()
        
        self.icons = {
            name: ImageTexture(*load_png(f"icons/{name}.png"))
            for name in ["brush", "ellipse", "floodfill", "line", "spray",
                         "pencil", "picker", "points", "rectangle"]
        }

        self.plugins = {}
        init_plugins(self)
        self.drawing.plugins = self.plugins

        self.show_only_current_layer = False
        self.layer_being_switched = False
        
    @property
    def tool(self):
        return self.tools.current

    @property
    def overlay(self):
        return self.view.overlay

    @property
    def brush(self):
        return self.view.brushes[-1] if self.view.brushes else self._brush
    
    @no_imgui_events
    def on_mouse_press(self, x, y, button, modifiers):
        if not self.drawing:
            return
        if self.mouse_event_queue:
            return
        if button in (pyglet.window.mouse.LEFT,
                      pyglet.window.mouse.RIGHT):

            self.view.overlay.clear_all()
            
            self.mouse_event_queue = Queue()
            x, y = self._to_image_coords(x, y)
            initial_point = int(x), int(y)
            self.mouse_event_queue.put(("mouse_down", initial_point, button, modifiers))
            if button == pyglet.window.mouse.LEFT:
                color = self.drawing.palette.foreground
            else:
                # Erasing always uses background color
                color = self.drawing.palette.background
            tool = self.tool(self.drawing, self.brush, color)
            # self.autosave_drawing.cancel()
            self.stroke = self.executor.submit(make_stroke, self.view, self.mouse_event_queue, tool)
            self.stroke.add_done_callback(lambda s: self.executor.submit(self._finish_stroke, s))
            self.stroke_tool = tool

    def on_mouse_release(self, x, y, button, modifiers):
        if self.mouse_event_queue:
            x, y = self._to_image_coords(x, y)
            pos = int(x), int(y)
            self.mouse_event_queue.put(("mouse_up", pos, button, modifiers))

    def on_mouse_motion(self, x, y, dx, dy):
        "Callback for mouse motion without buttons held"
        if self.stroke or not self.view:
            return
        # self._update_cursor(x, y)
        # if self.tools.current.brush_preview:
        self._draw_brush_preview(x - dx, y - dy, x, y)

    def on_mouse_leave(self, x, y):
        if not self.stroke:
            self.overlay.clear_all()
        
    # @cache_clear(get_layer_preview_texture)
    @try_except_log
    def _finish_stroke(self, stroke):
        "Callback that gets run every time a stroke is finished."
        # Since this is a callback, stroke is a Future and is guaranteed to be finished.
        # self.stroke_tool = None
        tool = stroke.result()
        if tool and tool.rect:
            s = tool.rect.as_slice()
            # src = self.view.overlay.data[s]
            # dst = self.view.layer[s]
            # print(dir(dst))
            # np.copyto(dst, src, where=src > 255)
            self.view.modify(self.view.layer_index, s, self.view.overlay.data[s], tool)
            self.view.overlay.clear(tool.rect)
            self.view.dirty[self.view.layer_index] = tool.rect
        else:
            # If no rect is set, the tool is presumed to not have changed anything.
            self.view.overlay.clear_all()
        self.mouse_event_queue = None
        self.stroke = None
        # self.autosave_drawing()
        print("Stroke finished")
        
    @no_imgui_events
    def on_mouse_drag(self, x, y, dx, dy, button, modifiers):
        "Callback for mouse movement with buttons held"
        if self.stroke:
            # Add to ongoing stroke
            x, y = self._to_image_coords(x, y)
            ipos = int(x), int(y)
            self.mouse_event_queue.put(("mouse_drag", ipos, button, modifiers))
        elif button == pyglet.window.mouse.MIDDLE:
            # Pan image
            ox, oy = self.offset
            self.offset = ox + dx, oy + dy
            self._to_image_coords.cache_clear()
            
    @no_imgui_events
    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        if self.keys[key.LSHIFT]:
            if scroll_y > 0:
                self.view.next_layer()
            else:
                self.view.prev_layer()
        else:
            ox, oy = self.offset
            ix, iy = self._to_image_coords(x, y)
            self.zoom = max(min(self.zoom + scroll_y, MAX_ZOOM), MIN_ZOOM)
            self._to_image_coords.cache_clear()
            x2, y2 = self._to_window_coords(ix, iy)
            self.offset = ox + (x - x2), oy + (y - y2)
            self._to_image_coords.cache_clear()
            
    def on_key_press(self, symbol, modifiers):

        if symbol == key.LEFT:
            self.view.rotate(dz=-1)
        elif symbol == key.RIGHT:
            self.view.rotate(dz=1)
        elif symbol == key.UP:
            self.view.rotate(dx=-1)
        elif symbol == key.DOWN:
            self.view.rotate(dx=1)
        
        elif symbol == key.W:
            if modifiers & key.MOD_SHIFT:
                self.view.move_layer(1)
            else:
                self.view.next_layer()
                self.layer_being_switched = True
        elif symbol == key.S:
            if modifiers & key.MOD_SHIFT:
                self.view.move_layer(-1)
            elif modifiers & key.MOD_CTRL:
                self.drawing.to_ora("/tmp/hej.ora")
            else:
                self.view.prev_layer()
                self.layer_being_switched = True
        elif symbol == key.O:
            self.show_only_current_layer = not self.show_only_current_layer
        
        elif symbol == key.P:
            self.tools.select(ToolName.pencil)
        elif symbol == key.L:
            self.tools.select(ToolName.line)
        elif symbol == key.F:
            self.tools.select(ToolName.floodfill)
        elif symbol == key.R:
            self.tools.select(ToolName.rectangle)
        elif symbol == key.I:
            self.tools.select(ToolName.picker)

        elif symbol == key.B:
            if modifiers & key.MOD_SHIFT:
                self.view.brushes.clear()
            else:
                self.view.make_brush()
            
        elif symbol == key.Z:
            self.view.undo()
        elif symbol == key.Y:
            self.view.redo()

        elif symbol == key.F4:
            init_plugins(self)

    def on_key_release(self, symbol, modifiers):
        if symbol in {key.S, key.W}:
            self.layer_being_switched = False
            
    def on_draw(self):
        self._render_view()
        self._render_gui()

    def _render_view(self):
        # gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glClearBufferfv(gl.GL_COLOR, 0, (gl.GLfloat * 4)(0.25, 0.25, 0.25, 1))
        data = self.view.data
        w, h, d = self.view.shape
        size = w, h
        ob = self._get_offscreen_buffer(size)
        colors = self._get_colors(self.drawing.palette)
        window_size = self.get_size()
        
        with vao, ob, draw_program:
            gl.glViewport(0, 0, w, h)

            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glClearBufferfv(gl.GL_COLOR, 0, EMPTY_COLOR)

            cursor_pos = self.view.layer_index
            overlay = self.view.overlay
            overlay_texture = self._get_overlay_texture(size)
            
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

                current = i == self.view.layer_index
                if not current and (self.layer_being_switched or self.show_only_current_layer):
                    continue
                                    
                tex = self._get_layer_texture(i, size)
                dirty = self.view.dirty[i]
                if dirty and self.drawing.lock.acquire(timeout=0.01):
                    layer = data[:, :, i]
                    layer_data = layer.tobytes("F")  # TODO maybe there's a better way?
                    gl.glTextureSubImage2D(tex.name, 0, 0, 0, w, h,
                                           gl.GL_RED_INTEGER, gl.GL_UNSIGNED_BYTE,
                                           layer_data)
                    self.view.dirty[i] = None
                with tex:
                    if i == cursor_pos:
                        second_texture = overlay_texture
                    else:
                        second_texture = self._get_empty_texture(size)
                    with second_texture:
                        gl.glUniform1f(1, 1)
                        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)

            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 4)

        vm = self._make_view_matrix(window_size, size, self.zoom, self.offset)
        gl.glViewport(0, 0, *window_size)

        self._update_border(self.view.shape)
        with self.border_vao, line_program:
            gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE, (gl.GLfloat*16)(*vm))
            r, g, b, _ = (0.5, 0.5, 0.5, 0)  # TODO Use transparent color from palette?
            gl.glUniform3f(1, r, g, b)
            gl.glDrawArrays(gl.GL_TRIANGLE_FAN, 0, 4)

        with self.vao, copy_program:
            # Draw the actual drawing
            with ob["color"]:
                gl.glEnable(gl.GL_BLEND)
                gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE, (gl.GLfloat*16)(*vm))
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)

        with self.border_vao, line_program:                
            gl.glUniform3f(1, 0., 0., 0.)
            gl.glLineWidth(1)
            gl.glDrawArrays(gl.GL_LINE_LOOP, 0, 4)

    def _render_gui(self):
        w, h = self.get_size()
        
        imgui.new_frame()
        with imgui.font(self._font):
            ui.render_palette_popup(self.drawing)
            ui.render_layers(self.view)
            render_plugins_ui(self)
            
        imgui.render()
        imgui.end_frame()
        self.imgui_renderer.render(imgui.get_draw_data())

        
        
    @lru_cache(1)
    def _to_image_coords(self, x, y):
        "Convert window coordinates to image coordinates."
        w, h, _ = self.view.shape
        ww, wh = self.get_size()
        scale = 2 ** self.zoom
        ox, oy = self.offset
        ix = (x - (ww / 2 + ox)) / scale + w / 2
        iy = -(y - (wh / 2 + oy)) / scale + h / 2
        return int(ix), int(iy)

    def _to_window_coords(self, x, y):
        "Convert image coordinates to window coordinates"
        w, h, _ = self.view.shape
        ww, wh = self.get_size()
        scale = 2 ** self.zoom
        ox, oy = self.offset
        wx = scale * (x - w / 2) + ww / 2 + ox
        wy = -(scale * (y - h / 2) - wh / 2 - oy)
        return int(wx), int(wy)

    @lru_cache(1)
    def _over_image(self, x, y):
        if self.drawing:
            ix, iy = self._to_image_coords(x, y)
            w, h = self.view.size
            return 0 <= ix < w and 0 <= iy < h
    
    @try_except_log
    def _draw_brush_preview(self, x0, y0, x, y):
        # io = imgui.get_io()
        # if io.want_capture_mouse:
        #     return
        if self.stroke:  # or not self._over_image(x, y):
            return
        ix0, iy0 = self._to_image_coords(x0, y0)
        ix, iy = self._to_image_coords(x, y)
        brush = self.brush
        bw, bh = brush.size
        cx, cy = brush.center
        old_rect = Rectangle((ix0 - cx, iy0 - cy), brush.size)
        self.overlay.clear(old_rect)
        pos = (ix, iy)
        self.overlay.blit_brush(brush, pos, self.drawing.palette.foreground)
    
    @lru_cache(1)
    def _make_view_matrix(self, window_size, size, zoom, offset):
        return make_view_matrix(window_size, size, zoom, offset)
    
    @lru_cache(1)
    def _get_offscreen_buffer(self, size):
        return FrameBuffer(size, textures=dict(color=Texture(size, unit=0)))
            
    @lru_cache(128)
    def _get_layer_texture(self, i, size):
        texture = ByteTexture(size=size)
        texture.clear()
        return texture

    @lru_cache(1)
    def _get_overlay_texture(self, size):
        texture = IntegerTexture(size=size, unit=1)
        texture.clear()
        return texture
    
    @lru_cache(1)
    def _get_colors(self, palette):
        colors = palette.colors
        float_colors = chain.from_iterable((r / 255, g / 255, b / 255, a / 255)
                                           for r, g, b, a in colors)
        return (gl.GLfloat*(4*256))(*float_colors)

    @lru_cache(1)
    def _get_empty_texture(self, size):
        texture = IntegerTexture(size, unit=1)
        texture.clear()
        return texture

    @lru_cache(1)
    def _update_border(self, shape):
        w, h, _ = shape
        x0, y0 = 0, 0
        x1, y1 = w, h
        w2 = w / 2
        h2 = h / 2
        xw0 = (x0 - w2) / w
        yw0 = (h2 - y0) / h
        xw1 = (x1 - w2) / w
        yw1 = (h2 - y1) / h
        self.border_vertices.vertex_buffer.write([
            ((xw0, yw0, 0),),
            ((xw1, yw0, 0),),
            ((xw1, yw1, 0),),
            ((xw0, yw1, 0),)
        ])

        
class OldpaintEventLoop(pyglet.app.EventLoop):

    "A tweaked event loop that lowers the idle refresh rate for less CPU heating."

    def idle(self):
        super().idle()
        return 0.05

    
if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("orafile", nargs="?")

    args = parser.parse_args()
    
    gl_config = pyglet.gl.Config(major_version=4, minor_version=5,  # Minimum OpenGL requirement
                                 double_buffer=False)  # Double buffering gives noticable cursor lag

    VoxpaintWindow(config=gl_config, path=args.orafile)
    pyglet.app.event_loop = OldpaintEventLoop()
    pyglet.app.run(0.02)
