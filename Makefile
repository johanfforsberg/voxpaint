build:
	git submodule init
	git submodule update
	cd fogl; bin/get_pyglet.sh
	python3 -m venv env
	env/bin/pip install -r ./requirements.txt
	env/bin/pip install -e ./fogl/pyglet
	env/bin/pip install -e ./fogl

run:
	env/bin/python -m voxpaint
