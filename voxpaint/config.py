import configparser
from pathlib import Path

from pluginbase import PluginBase
from xdg import XDG_CONFIG_HOME, XDG_CACHE_HOME

VOXPAINT_CONFIG_HOME = XDG_CONFIG_HOME / "voxpaint"
VOXPAINT_CONFIG_HOME.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = VOXPAINT_CONFIG_HOME / "voxpaint.ini"
CACHE_DIR = XDG_CACHE_HOME / "voxpaint"


def load_config():
    config_file = configparser.ConfigParser()
    config_file.read(CONFIG_FILE)
    config = {}
    if "window" in config_file:
        size = config_file["window"].get("size")
        w, h = [int(v) for v in size.split()]
        config["window_size"] = w, h
    else:
        config["window_size"] = 800, 600

    if "recent_files" in config_file:
        recent_files = config_file["recent_files"]
        config["recent_files"] = list(recent_files.values())
    else:
        config["recent_files"] = []

    return config


def save_config(window_size=None, recent_files=None):
    config_file = configparser.ConfigParser()
    config_file.read(CONFIG_FILE)
    if window_size:
        w, h = window_size
        config_file["window"] = {"size": f"{w} {h}"}
    if recent_files:
        config_file["recent_files"] = {
            f"file_{i}": filename
            for i, filename in enumerate(recent_files)
        }
    with open(CONFIG_FILE, "w") as f:
        config_file.write(f)


def get_drawing_cache_dir(drawing_path):
    dir_name = drawing_path.replace("/", "%")
    path = CACHE_DIR / dir_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_autosave_filename(drawing_path, keep=3):
    cache_dir = get_drawing_cache_dir(drawing_path)
    files = list(cache_dir.glob("*.ora"))
    file_nos = sorted(int(fn.name.split(".")[0]) for fn in files[-keep:])

    to_remove = file_nos[0:-(keep-1)]
    for fn in to_remove:
        (cache_dir / f"{fn}.ora").unlink()

    if file_nos:
        latest = file_nos[-1]
    else:
        latest = -1
    return cache_dir / f"{latest + 1}.ora"


VOXPAINT_PLUGIN_DIR = Path(__file__).parent.parent / "plugins"
VOXPAINT_USER_PLUGIN_DIR = VOXPAINT_CONFIG_HOME / "plugins"
VOXPAINT_USER_PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
plugin_base = PluginBase(package='voxpaint.plugins')
plugin_source = plugin_base.make_plugin_source(searchpath=[str(VOXPAINT_PLUGIN_DIR),
                                                           str(VOXPAINT_USER_PLUGIN_DIR)])
