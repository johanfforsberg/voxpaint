from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from functools import lru_cache
import os
from queue import Queue

import imgui
import pyglet
from pyglet import gl
from pyglet.window import key

from fogl.shader import Program, VertexShader, FragmentShader
from fogl.texture import Texture, ByteTexture, ImageTexture
from fogl.util import load_png
from fogl.vao import VertexArrayObject
from fogl.vertex import SimpleVertices

from .brush import Brush
from .constants import ToolName
from .drawing import Drawing, DrawingView
from .imgui_pyglet import PygletRenderer
from .palette import Palette
from .plugin import init_plugins, render_plugins_ui
from .rect import Rectangle
from .render import render_view
from .stroke import make_stroke
from .tool import (PencilTool, PointsTool, SprayTool,
                   LineTool, RectangleTool, EllipseTool,
                   SelectionTool, ColorPickerTool, LayerPickerTool, FillTool)
from . import ui
from .util import (make_view_matrix, try_except_log, Selectable, Selectable2, no_imgui_events,
                   show_load_dialog, show_save_dialog, cache_clear, debounce)


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

    def __init__(self, recent_files, *args, path=None, **kwargs):
        
        super().__init__(*args, **kwargs, resizable=True, vsync=False)

        self.recent_files = OrderedDict((k, None) for k in recent_files)
        
        if path:
            self.drawings = Selectable([Drawing.from_ora(path)])
        else:
            # self.drawing = Drawing((640, 480, 10), palette=Palette())
            self.drawings = Selectable([Drawing((128, 128, 128), palette=Palette())])
        self._views = {}
        
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
            for tool in [
                    PencilTool, PointsTool, SprayTool,
                    LineTool, RectangleTool,
                    # EllipseTool,
                    FillTool,
                    # SelectionTool,
            ]
        })
        self.temp_tool = None
        
        self._brush = Brush((1, 1))
        self.stroke = None

        self.executor = ThreadPoolExecutor(max_workers=1)
        self.mouse_event_queue = None

        self.vao = VertexArrayObject()
        
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

    @property
    def drawing(self):
        return self.drawings.current
    
    @property
    def view(self):
        view = self._views.get(self.drawing)
        if view:
            return view
        view = self.drawing.get_view()
        self._views[self.drawing] = view
        return view

    @property
    def tool(self):
        return self.temp_tool or self.tools.current

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
        if self.tool.brush_preview:
            self._draw_brush_preview(x - dx, y - dy, x, y)

    def on_mouse_leave(self, x, y):
        if not self.stroke:
            self.overlay.clear_all()
                
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
            self.view.layer_being_switched = True
        else:
            ox, oy = self.offset
            ix, iy = self._to_image_coords(x, y)
            self.zoom = max(min(self.zoom + scroll_y, MAX_ZOOM), MIN_ZOOM)
            self._to_image_coords.cache_clear()
            x2, y2 = self._to_window_coords(ix, iy)
            self.offset = ox + (x - x2), oy + (y - y2)
            self._to_image_coords.cache_clear()
            
    def on_key_press(self, symbol, modifiers):

        print("press", symbol, modifiers)

        if symbol in {key.LEFT, key.A}:
            self.view.rotate(dz=-1)
        elif symbol in {key.RIGHT, key.D}:
            self.view.rotate(dz=1)
            
        elif symbol in {key.UP, key.W}:
            if modifiers & key.MOD_SHIFT:
                self.view.move_layer(1)
            else:
                self.view.rotate(dx=-1)
        elif symbol in {key.DOWN, key.S}:
            if modifiers & key.MOD_SHIFT:
                self.view.move_layer(-1)
            else:
                self.view.rotate(dx=1)
        
        # elif symbol == key.W:
        #     if modifiers & key.MOD_SHIFT:
        #         self.view.move_layer(1)
        #     else:
        #         self.view.next_layer()
        #         self.view.layer_being_switched = True
        # elif symbol == key.S:
        #     if modifiers & key.MOD_SHIFT:
        #         self.view.move_layer(-1)
        #     elif modifiers & key.MOD_CTRL:
        #         self.drawing.to_ora("/tmp/hej.ora")
        #     else:
        #         self.view.prev_layer()
        #         self.view.layer_being_switched = True
        
        elif symbol == key.O:
            self.view.show_only_current_layer = not self.view.show_only_current_layer
        
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
                self.view.overlay.clear_all()
            else:
                self.view.make_brush()
                self.view.overlay.clear_all()
            
        elif symbol == key.Z:
            self.view.undo()
        elif symbol == key.Y:
            self.view.redo()

        elif symbol in {key.LSHIFT, key.RSHIFT}:
            self.temp_tool = LayerPickerTool
            self.overlay.clear_all()
        elif symbol in {key.LCTRL, key.RCTRL}:
            self.temp_tool = ColorPickerTool
            self.overlay.clear_all()
            
        elif symbol == key.F4:
            init_plugins(self)

    def on_key_release(self, symbol, modifiers):

        print("release", symbol, modifiers)        
        
        if symbol in {key.S, key.W}:
            self.view.layer_being_switched = False
            
        elif symbol in {key.LSHIFT, key.RSHIFT, key.LCTRL, key.RCTRL}:
            self.view.layer_being_switched = False
            self.temp_tool = None
            
    def on_draw(self):
        self._render_view()
        self._render_gui()

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
        
    def _render_view(self):
        # gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glClearBufferfv(gl.GL_COLOR, 0, (gl.GLfloat * 4)(0.25, 0.25, 0.25, 1))
        w, h, d = self.view.shape
        size = w, h
        window_size = self.get_size()
        
        ob = render_view(self)
        
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
            ui.render_menu(self)
            render_plugins_ui(self)
            
        imgui.render()
        imgui.end_frame()
        self.imgui_renderer.render(imgui.get_draw_data())
        
    @try_except_log
    def save_drawing(self, drawing=None, ask_for_path=False, auto=False):
        "Save the drawing, asking for a file name if neccessary."
        drawing = drawing or self.drawing
        if not ask_for_path and drawing.path:
            drawing.save()
            self._add_recent_file(drawing.path)
            # elif drawing.path.endswith(".png") and len(drawing.layers) == 1:
            #     drawing.save_png()
        else:
            last_dir = self._get_latest_dir()
            # The point here is to not block the UI redraws while showing the
            # dialog. May be a horrible idea but it seems to work...
            fut = self.executor.submit(show_save_dialog,
                                       title="Select file",
                                       initialdir=last_dir,
                                       filetypes=(("ORA files", "*.ora"),
                                                  # ("PNG files", "*.png"),
                                                  ("all files", "*.*")))

            def really_save_drawing(drawing, path):
                try:
                    if path:
                        try:
                            drawing.save(path)
                            self._add_recent_file(path)
                        except (AssertionError, ValueError) as e:
                            print(e)
                            self._error = str(e)
                except OSError as e:
                    self._error = f"Could not save:\n {e}"

            fut.add_done_callback(
                lambda fut: really_save_drawing(drawing, fut.result()))

    def load_drawing(self, path=None):

        def really_load_drawing(path):
            if path:
                if path.endswith(".ora"):
                    drawing = Drawing.from_ora(path)
                elif path.endswith(".png"):
                    drawing = Drawing.from_png(path)
                self.drawings.append(drawing)
                self.drawings.select(drawing)
                print("hej", drawing)
                self._add_recent_file(path)

        if path:
            really_load_drawing(path)
        else:
            last_dir = self._get_latest_dir()
            fut = self.executor.submit(show_load_dialog,
                                       title="Select file",
                                       initialdir=last_dir,
                                       filetypes=(("All image files", "*.ora"),
                                                  ("All image files", "*.png"),
                                                  ("ORA files", "*.ora"),
                                                  ("PNG files", "*.png"),
                                                  ))
            fut.add_done_callback(
                lambda fut: really_load_drawing(fut.result()))
            
    def _get_latest_dir(self):
        if self.recent_files:
            f = list(self.recent_files.keys())[-1]
            return os.path.dirname(f)

    def _add_recent_file(self, filename, maxsize=10):
        print("add recent file", filename)
        self.recent_files[filename] = None
        if len(self.recent_files) > maxsize:
            for f in self.recent_files:
                del self.recent_files[f]
                break
            
    @lru_cache(1)
    def _make_view_matrix(self, window_size, size, zoom, offset):
        return make_view_matrix(window_size, size, zoom, offset)
        
    @lru_cache(1)
    def _to_image_coords(self, x, y):
        "Convert window coordinates to image coordinates."
        w, h, _ = self.view.shape
        ww, wh = self.get_size()
        scale = 2 ** self.zoom
        ox, oy = self.offset
        ix = (x - (ww / 2 + ox)) / scale + w / 2
        iy = -(y - (wh / 2 + oy)) / scale + h / 2
        return ix, iy

    def _to_window_coords(self, x, y):
        "Convert image coordinates to window coordinates"
        w, h, _ = self.view.shape
        ww, wh = self.get_size()
        scale = 2 ** self.zoom
        ox, oy = self.offset
        wx = scale * (x - w / 2) + ww / 2 + ox
        wy = -(scale * (y - h / 2) - wh / 2 - oy)
        return wx, wy

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
        print(xw0, yw0, xw1, yw1)
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