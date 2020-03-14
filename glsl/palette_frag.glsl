#version 450 core

precision lowp float;

layout (binding = 0) uniform usampler2D image;
layout (binding = 1) uniform usampler2D overlay;

layout (location = 1) uniform float global_alpha = 1;
layout (location = 2) uniform vec4[256] palette;

in VS_OUT {
  vec2 texcoord;
} fs_in;

layout (location=0) out vec4 color;

void main(void) {
  uvec4 pixel = texture(image, fs_in.texcoord);
  uvec4 over_pixel = texture(overlay, fs_in.texcoord);
  uint index;
  if (over_pixel.a > 0) {
    index = over_pixel.r;
    vec4 color_ = palette[index];
    if (color_.a == 0)
      discard;
    color = vec4(color_.rgb, global_alpha);
  } else {
    index = pixel.r;
    vec4 color_ = palette[index];
    if (pixel.a == 0 || color_.a == 0)
      discard;
    color = vec4(color_.rgb, global_alpha);
  }
}
