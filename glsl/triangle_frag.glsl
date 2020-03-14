#version 450 core

layout (location = 1) uniform vec3 line_color = vec3(1, 1, 0);

out vec4 color;

void main(void) {
  //color = vec4(0.0, 0.8, 1.0, 1.0);
  color = vec4(line_color, 1);
}
