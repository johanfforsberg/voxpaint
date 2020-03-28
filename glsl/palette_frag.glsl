#version 450 core

precision lowp float;

layout (binding = 0) uniform usampler2DArray image;
layout (binding = 1) uniform usampler2D overlay;

layout (location = 1) uniform float global_alpha = 1;
layout (location = 2) uniform ivec2 slice;
layout (location = 3) uniform uint transparent_color = 0;
layout (location = 4) uniform vec4[256] palette;

in VS_OUT {
  vec2 texcoord;
} fs_in;

layout (location=0) out vec4 color;


void main(void) {
  uvec4 over_pixel = texture(overlay, fs_in.texcoord);
  uint index;
  if (over_pixel.a > 0) {
    index = over_pixel.r;
    vec4 color_ = palette[index];
    if (color_.a == 0) {
      discard;
    }
    color = vec4(color_.rgb, global_alpha);
  } else {
    uvec4 pixel;
    int depth = slice[1] - slice[0];
    for (int i = 0; i < depth; i++) {
      // TODO Could not get the loop to work counting down; am I stupid or is this a limitation?
      pixel = texture(image, vec3(fs_in.texcoord, slice[1] - 1 - i));
      if (pixel.r != transparent_color) {
        // Take the topmost non transparent pixel.
        break;
      }
    } 
    index = pixel.r;
    vec4 color_ = palette[index];
    if (pixel.a == 0 || color_.a == 0)
      discard;
    color = vec4(color_.rgb, global_alpha);
  }
}
