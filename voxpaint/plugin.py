"""
Plugin architecture. Currently very minimal, hacky and fragile.
The plugin API is also not stable.
"""

import inspect
import imp
from itertools import islice
from logging import getLogger
from time import time
from traceback import print_exc

import imgui
import voxpaint

from .config import plugin_source
from .util import try_except_log


logger = getLogger("voxpaint").getChild("plugins")


def init_plugins(window):
    "(Re)initialize all found plugins"
    plugins = plugin_source.list_plugins()
    for plugin_name in plugins:
        logger.info("Initializing plugin: %s", plugin_name)
        try:
            plugin = plugin_source.load_plugin(plugin_name)
            if plugin_name in window.plugins:
                imp.reload(plugin)
            # TODO more sophisticated way of handling the different kinds of plugin
            if hasattr(plugin, "plugin"):
                # Simple function plugin
                sig = inspect.signature(plugin.plugin)
                window.plugins[plugin_name] = plugin.plugin, sig.parameters, {}
            elif hasattr(plugin, "Plugin"):
                # Class plugin
                sig = inspect.signature(plugin.Plugin.__call__)
                params = dict(islice(sig.parameters.items(), 1, None))
                # TODO Broken if plugin is active for more than one drawing!
                # Need one instance per drawing.
                window.plugins[plugin_name] = plugin.Plugin(), params, {}
        except Exception:
            print_exc()
            

@try_except_log
def render_plugins_ui(window):
    "Draw UI windows for all plugins active for the current drawing."
    if not window.drawing:
        return
    
    deactivated = set()
    for name in window.drawing.plugins:
        plugin, sig, args = window.plugins[name]
        _, opened = imgui.begin(name, True)
        if not opened:
            deactivated.add(name)
        imgui.columns(2)
        for param_name, param_sig in islice(sig.items(), 3, None):
            imgui.text(param_name)
            imgui.next_column()
            default_value = args.get(param_name)
            if default_value is not None:
                value = default_value
            else:
                value = param_sig.default
            label = f"##{param_name}_val"
            if param_sig.annotation == int:
                changed, args[param_name] = imgui.drag_int(label, value)
            elif param_sig.annotation == float:
                changed, args[param_name] = imgui.drag_float(label, value)
            elif param_sig.annotation == str:
                changed, args[param_name] = imgui.input_text(label, value, 20)
            elif param_sig.annotation == bool:
                changed, args[param_name] = imgui.checkbox(label, value)
            imgui.next_column()
        imgui.columns(1)

        texture_and_size = getattr(plugin, "texture", None)
        if texture_and_size:
            texture, size = texture_and_size
            w, h = size
            ww, wh = imgui.get_window_size()
            scale = max(1, (ww - 10) // w)
            imgui.image(texture.name, w*scale, h*scale, border_color=(1, 1, 1, 1))

        last_run = getattr(plugin, "last_run", 0)
        period = getattr(plugin, "period", None)
        t = time()
        if period and t > last_run + period or imgui.button("Execute"):
            plugin.last_run = last_run
            try:
                result = plugin(voxpaint, window.drawing, **args)
                if result:
                    args.update(result)
            except Exception:
                print_exc()

        imgui.button("Help")
        if imgui.begin_popup_context_item("Help", mouse_button=0):
            if plugin.__doc__:
                imgui.text(inspect.cleandoc(plugin.__doc__))
            else:
                imgui.text("No documentation available.")
            imgui.end_popup()

        imgui.end()
    for name in deactivated:
        window.drawing.active_plugins.pop(name, None)
