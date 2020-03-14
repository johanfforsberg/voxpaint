#version 450 core

uniform sampler2D tex;

in VS_OUT {
  vec2 texcoord;
} fs_in;

out vec4 color;

void main(void) {
  //color = vec4(0.0, 0.8, 1.0, 1.0);
  color = texture(tex, fs_in.texcoord);
}
