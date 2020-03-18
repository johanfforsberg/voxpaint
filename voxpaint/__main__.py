import pyglet
import pyximport
pyximport.install(language_level=3)  # Setup cython to autocompile pyx modules

from .config import load_config, save_config
from .window import VoxpaintWindow


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
    
    config = load_config()
    width, height = config["window_size"]
    
    window = VoxpaintWindow(width=width, height=height, recent_files=config["recent_files"],
                            config=gl_config, path=args.orafile)

    pyglet.app.event_loop = OldpaintEventLoop()
    pyglet.app.run(0.02)
    
    save_config(window_size=window.get_size(),
                recent_files=window.recent_files.keys())
