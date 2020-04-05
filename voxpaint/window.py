from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from functools import lru_cache
from typing import Tuple
from traceback import print_exc
import os
from queue import Queue

from euclid3 import Matrix4, Vector3
import imgui
import pyglet
from pyglet import gl
from pyglet.window import key

from fogl.shader import Program, VertexShader, FragmentShader
from fogl.texture import ImageTexture
from fogl.util import load_png
from fogl.vao import VertexArrayObject
from fogl.vertex import SimpleVertices

from .brush import Brush
from .config import get_autosave_filename
from .constants import ToolName
from .drawing import Drawing
from .imgui_pyglet import PygletRenderer
from .plugin import init_plugins, render_plugins_ui
from .rect import Rectangle
from .render import render_view
from .stroke import make_stroke
from .tool import (PencilTool, PointsTool, SprayTool,
                   LineTool, RectangleTool,  # EllipseTool,
                   SelectionTool, ColorPickerTool, LayerPickerTool, FillTool)
from . import ui
from .util import (make_view_matrix, try_except_log, Selectable, Selectable2, no_imgui_events,
                   show_load_dialog, show_save_dialog, debounce)


EMPTY_COLOR = (gl.GLfloat * 4)(0, 0, 0, 0)


MIN_ZOOM = -2
MAX_ZOOM = 5


class VoxpaintWindow(pyglet.window.Window):

    def __init__(self, recent_files, *args, path=None, **kwargs):
        
        super().__init__(*args, **kwargs, caption="Voxpaint", resizable=True, vsync=False)

        self.recent_files = OrderedDict((k, None) for k in recent_files)

        self.vao = VertexArrayObject()

        self.draw_program = Program(VertexShader("glsl/palette_vert.glsl"),
                                    FragmentShader("glsl/palette_frag.glsl"))

        self.copy_program = Program(VertexShader("glsl/copy_vert.glsl"),
                                    FragmentShader("glsl/copy_frag.glsl"))

        self.line_program = Program(VertexShader("glsl/triangle_vert.glsl"),
                                    FragmentShader("glsl/triangle_frag.glsl"))
        
        if path:
            self.drawings = Selectable([Drawing.from_ora(path)], on_change=lambda d: d.all_dirty())
        else:
            self.drawings = Selectable(on_change=lambda d: d.all_dirty())
        self.exit_unsaved_drawings = None
        self.close_unsaved_drawing = None
        self._views = {}
        
        self.keys = key.KeyStateHandler()
        self.push_handlers(self.keys)

        self.border_vao = VertexArrayObject(vertices_class=SimpleVertices)
        self._border_vertices = self.border_vao.create_vertices(
            [((0, 0, 0),),
             ((0, 0, 0),),
             ((0, 0, 0),),
             ((0, 0, 0),)])
        self.tool_rect_vao = VertexArrayObject(vertices_class=SimpleVertices)        
        self._tool_rect_vertices = self.tool_rect_vao.create_vertices(
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
                    SelectionTool,
            ]
        })
        self.temp_tool = None
        
        self._brush = Brush((1, 1))
        self.stroke = None
        self.stroke_tool = None

        self._error = None

        self.mouse_position = None

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
        self.mouse_texture = ImageTexture(*load_png("icons/cursor.png"))

        self.plugins = {}
        init_plugins(self)

    @property
    def drawing(self):
        return self.drawings.current
        
    @property
    def view(self):
        if not self.drawing:
            return
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
        if self.drawing:
            return self.view.overlay

    @property
    def brush(self):
        if self.drawing:
            return self.drawing.brush or self._brush

    @property
    def zoom(self):
        return self.view.zoom

    @zoom.setter
    def zoom(self, value):
        self.view.zoom = value

    @property
    def offset(self):
        return self.view.offset

    @offset.setter
    def offset(self, value):
        self.view.offset = value        
        
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
            self.autosave_drawing.cancel()
            self.stroke = self.executor.submit(make_stroke, self.view, self.mouse_event_queue, tool)
            self.stroke.add_done_callback(lambda s: self.executor.submit(self._finish_stroke, s))
            self.stroke_tool = tool

    # @cache_clear(get_layer_preview_texture)
    @try_except_log
    def _finish_stroke(self, stroke):
        "Callback that gets run every time a stroke is finished."
        # Since this is a callback, stroke is a Future and is guaranteed to be finished.
        self.stroke_tool = None
        tool = stroke.result()
        if tool and tool.rect:
            s = tool.rect.as_slice()
            self.view.modify_layer(self.view.layer_index, tool.rect, self.view.overlay.data[s], tool)
            self.view.overlay.clear(tool.rect)
            # self.view.dirty[self.view.layer_index] = tool.rect
        else:
            # If no rect is set, the tool is presumed to not have changed anything.
            self.view.overlay.clear_all()
        self.mouse_event_queue = None
        self.stroke = None
        if tool.restore_last:
            self.tools.restore()
        self.autosave_drawing()
            
    def on_mouse_release(self, x, y, button, modifiers):
        if self.mouse_event_queue:
            x, y = self._to_image_coords(x, y)
            pos = int(x), int(y)
            self.mouse_event_queue.put(("mouse_up", pos, button, modifiers))

    def on_mouse_motion(self, x, y, dx, dy):
        "Callback for mouse motion without buttons held"
        if self.stroke or not self.view:
            return
        self._update_cursor(x, y)
        if self.tool.brush_preview:
            self._draw_brush_preview(x - dx, y - dy, x, y)

    def on_mouse_leave(self, x, y):
        if not self.stroke and self.drawing:
            self.overlay.clear_all()
        self.mouse_position = None
                
    @no_imgui_events
    def on_mouse_drag(self, x, y, dx, dy, button, modifiers):
        "Callback for mouse movement with buttons held"
        if (x, y) == self.mouse_position:
            # The mouse hasn't actually moved; do nothing
            return      
        self._update_cursor(x, y)
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

        if symbol in {key.LEFT, key.A}:
            self.view.rotate(dz=-1)
        elif symbol in {key.RIGHT, key.D}:
            self.view.rotate(dz=1)
        elif symbol in {key.UP}:
            self.view.rotate(dx=-1)
        elif symbol in {key.DOWN}:
            self.view.rotate(dx=1)        
            
        elif symbol in {key.W}:
            if modifiers & key.MOD_SHIFT:
                self.view.move_layer(1)
            else:
                self.view.next_layer()
        elif symbol in {key.S}:
            if modifiers & key.MOD_SHIFT:
                self.view.move_layer(-1)
            else:
                self.view.prev_layer()
                
        elif symbol == key.V:
            self.view.toggle_layer()
        elif symbol == key.O:
            self.view.show_only_current_layer = not self.view.show_only_current_layer
        
        elif symbol == key.P:
            self.tools.select(ToolName.pencil)
        elif symbol == key.L:
            self.tools.select(ToolName.line)
        elif symbol == key.F:
            self.tools.select(ToolName.floodfill)
            self.overlay and self.overlay.clear_all()
        elif symbol == key.R:
            self.tools.select(ToolName.rectangle)
        elif symbol == key.B:
            if modifiers & key.MOD_SHIFT:
                self.view.make_brush()
            else:
                self.tools.select(ToolName.brush)
            self.overlay and self.overlay.clear_all()
            
        elif symbol == key.Z:
            self.view.undo()
        elif symbol == key.Y:
            self.view.redo()

        elif symbol in {key.LSHIFT, key.RSHIFT}:
            self.temp_tool = LayerPickerTool
            self.overlay and self.overlay.clear_all()
        elif symbol in {key.LCTRL, key.RCTRL}:
            self.temp_tool = ColorPickerTool
            self.overlay and self.overlay.clear_all()
            
        elif symbol == key.F4:
            init_plugins(self)
        elif symbol == key.F5:
            self.drawing.dirty = tuple(slice(0, c) for c in self.drawing.shape)

        elif symbol == key.ESCAPE:
            if self.drawing:
                self.drawing.brushes.select(None)
                self.overlay.clear_all()

    def on_key_release(self, symbol, modifiers):

        if symbol in {key.LSHIFT, key.RSHIFT, key.LCTRL, key.RCTRL}:
            self.temp_tool = None
            
    def on_draw(self):
        self._render_view()
        self._render_gui()
        gl.glFinish()  # TODO This seems important; figure out why and if it's the best way.

    def on_close(self):
        self._quit()
        
    def _render_view(self):

        gl.glClearBufferfv(gl.GL_COLOR, 0, (gl.GLfloat * 4)(0.25, 0.25, 0.25, 1))

        if not self.view:
            return
        
        w, h, d = self.view.shape
        size = w, h
        window_size = self.get_size()

        ob = render_view(self)
        
        vm = make_view_matrix(window_size, size, self.zoom, self.offset)
        vm = (gl.GLfloat*16)(*vm)
        gl.glViewport(0, 0, *window_size)

        self._update_border(self.view.shape)
        with self.border_vao, self.line_program:
            gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE, vm)
            r, g, b, a = self.drawing.palette.colors[0]  # Color 0 is currently hardcoded background
            gl.glUniform3f(1, r/256, g/256, b/256)
            gl.glDrawArrays(gl.GL_TRIANGLE_FAN, 0, 4)

        with self.vao, self.copy_program:
            # Draw the actual drawing
            with ob["color"]:
                gl.glEnable(gl.GL_BLEND)
                gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE, (gl.GLfloat*16)(*vm))
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
            self._draw_mouse_cursor()            

        with self.border_vao, self.line_program:                
            gl.glUniform3f(1, 0., 0., 0.)
            gl.glLineWidth(1)
            gl.glDrawArrays(gl.GL_LINE_LOOP, 0, 4)

        if self.stroke_tool and self.stroke_tool.show_rect:
            if self.stroke_tool.rect:
                self._update_tool_rect(self.stroke_tool.rect)
                with self.tool_rect_vao, self.line_program:
                    gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE, vm)
                    gl.glUniform3f(1, 1., 1., 0.)
                    gl.glLineWidth(1)
                    gl.glDrawArrays(gl.GL_LINE_LOOP, 0, 4)            

    def _render_gui(self):
        w, h = self.get_size()
        
        imgui.new_frame()
        with imgui.font(self._font):
            
            ui.render_menu(self)

            if self.drawing:
            
                imgui.set_next_window_size(115, h - 20)
                imgui.set_next_window_position(w - 115, 20)

                imgui.begin("Sidebar", False, flags=(imgui.WINDOW_NO_TITLE_BAR
                                                     | imgui.WINDOW_NO_RESIZE
                                                     | imgui.WINDOW_NO_MOVE))

                ui.render_tools(self.tools, self.icons)
                imgui.separator()

                ui.render_palette(self.drawing)
                imgui.separator()
                
                ui.render_layers(self.view)

                imgui.end()

                ui.render_unsaved_exit(self)
                ui.render_unsaved_close_drawing(self)
                
                render_plugins_ui(self.drawing)
                
            ui.render_new_drawing_popup(self)

            if self._error:
                imgui.open_popup("Error")
                if imgui.begin_popup_modal("Error")[0]:
                    imgui.text(self._error)
                    if imgui.button("Doh!"):
                        self._error = None
                        imgui.close_current_popup()
                    imgui.end_popup()
            
        imgui.render()
        imgui.end_frame()
        data = imgui.get_draw_data()
        self.imgui_renderer.render(data)

    def _quit(self):
        unsaved = [d for d in self.drawings if d.unsaved]
        if unsaved:
            self.exit_unsaved_drawings = unsaved
        else:
            pyglet.app.exit()
        
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
                            print_exc()
                            self._error = str(e)
                except OSError as e:
                    self._error = f"Could not save:\n {e}"

            fut.add_done_callback(
                lambda fut: really_save_drawing(drawing, fut.result()))

    @debounce(cooldown=60, wait=3)
    def autosave_drawing(self):

        @try_except_log
        def really_autosave():
            path = self.drawing.path or self.drawing.uuid
            auto_filename = get_autosave_filename(path)
            print(f"Autosaving to {auto_filename}...")
            self.drawing.save(str(auto_filename), auto=True)

        fut = self.executor.submit(really_autosave)
        fut.add_done_callback(lambda fut: print("Autosave done!"))
            
    def load_drawing(self, path=None):

        def really_load_drawing(path):
            if path:
                try:
                    if path.endswith(".ora"):
                        drawing = Drawing.from_ora(path)
                    elif path.endswith(".png"):
                        drawing = Drawing.from_png(path)
                    self.drawings.append(drawing)
                    self.drawings.select(drawing)
                    self._add_recent_file(path)
                except NotImplementedError as nie:
                    self._error = str(nie)

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

    _new_drawing = None
            
    def create_drawing(self):
        shape = self.drawing.shape if self.drawing else (64, 64, 64)
        self._new_drawing = dict(shape=shape)

    def really_create_drawing(self):
        drawing = Drawing(size=self._new_drawing["shape"])
        self.drawings.append(drawing)
        self._new_drawing = None

    def close_drawing(self):
        drawing = self.drawing
        if drawing.unsaved:
            self.close_unsaved_drawing = drawing
        else:
            self.drawings.remove(drawing)
            
    def _get_latest_dir(self):
        if self.recent_files:
            f = list(self.recent_files.keys())[-1]
            return os.path.dirname(f)

    def _add_recent_file(self, filename, maxsize=10):
        self.recent_files.pop(filename, None)
        self.recent_files[filename] = None
        if len(self.recent_files) > maxsize:
            for f in self.recent_files:
                del self.recent_files[f]
                break
            
    @lru_cache(1)
    def _to_image_coords(self, x: float, y: float) -> Tuple[float, float]:
        "Convert window coordinates to image coordinates."
        w, h, _ = self.view.shape
        ww, wh = self.get_size()
        scale = 2 ** self.zoom
        ox, oy = self.offset
        ix = (x - (ww / 2 + ox)) / scale + w / 2
        iy = -(y - (wh / 2 + oy)) / scale + h / 2
        return ix, iy

    def _to_window_coords(self, x: float, y: float) -> Tuple[float, float]:
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

    def _draw_mouse_cursor(self):
        """ If the mouse is over the image, draw a cursom crosshair. """
        if self.mouse_position is None:
            return
        x, y = self.mouse_position
        w, h = self.get_size()
        vm = self._make_cursor_view_matrix(x, y)
        with self.mouse_texture:
            gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glUniformMatrix4fv(0, 1, gl.GL_FALSE, (gl.GLfloat*16)(*vm))
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
            gl.glBlendFunc(gl.GL_ONE, gl.GL_ZERO)

    @lru_cache(1)
    def _make_cursor_view_matrix(self, x, y):

        "Calculate a view matrix for placing the custom cursor on screen."

        ww, wh = self.get_size()
        iw, ih = self.mouse_texture.size

        scale = 1
        width = ww / iw / scale
        height = wh / ih / scale
        far = 10
        near = -10

        frust = Matrix4()
        frust[:] = (2/width, 0, 0, 0,
                    0, 2/height, 0, 0,
                    0, 0, -2/(far-near), 0,
                    0, 0, -(far+near)/(far-near), 1)

        x -= ww / 2
        y -= wh / 2
        lx = x / iw / scale
        ly = y / ih / scale

        view = Matrix4().new_translate(lx, ly, 0)

        return frust * view
            
    @try_except_log
    def _draw_brush_preview(self, x0, y0, x, y):

        if not self.drawing:
            return
        
        if self.stroke:  # or not self._over_image(x, y):
            return

        # TODO This is pretty crude; keep track of the preview to be able to clear it.
        ix0, iy0 = self._to_image_coords(x0, y0)
        brush = self.brush
        bw, bh = brush.size
        cx, cy = brush.center
        old_rect = Rectangle((int(ix0 - cx), int(iy0 - cy)), brush.size)
        self.overlay.clear(old_rect)

        io = imgui.get_io()
        if io.want_capture_mouse:
            return
        
        ix, iy = self._to_image_coords(x, y)
        pos = (int(ix), int(iy))
        self.overlay.blit_brush(brush, pos, self.drawing.palette.foreground)
    
    def _update_cursor(self, x, y):
        over_image = self._over_image(x, y)
        if over_image:
            io = imgui.get_io()
            if io.want_capture_mouse:
                self.mouse_position = None
                self.set_mouse_visible(True)
            else:
                self.mouse_position = x, y
                self.set_mouse_visible(False)
        else:
            self.mouse_position = None
            self.set_mouse_visible(True)
    
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
        self._border_vertices.vertex_buffer.write([
            ((xw0, yw0, 0),),
            ((xw1, yw0, 0),),
            ((xw1, yw1, 0),),
            ((xw0, yw1, 0),)
        ])

    @lru_cache(1)
    def _update_tool_rect(self, rect):
        w, h = self.view.size
        rw, rh = rect.size
        x0, y0 = rect.position
        x1, y1 = x0 + rw, y0 + rh
        w2 = w / 2
        h2 = h / 2
        xw0 = (x0 - w2) / w
        yw0 = (h2 - y0) / h
        xw1 = (x1 - w2) / w
        yw1 = (h2 - y1) / h
        self._tool_rect_vertices.vertex_buffer.write([
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
