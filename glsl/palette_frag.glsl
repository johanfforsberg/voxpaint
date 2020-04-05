#version 450 core

precision lowp float;

layout (binding = 0) uniform usampler2DArray image;
layout (binding = 1) uniform usampler2D overlay;

layout (location = 2) uniform float global_alpha = 1;
layout (location = 3) uniform ivec2 slice;
layout (location = 4) uniform uint transparent_color = 0;
layout (location = 5) uniform vec4[256] palette;

in VS_OUT {
  vec4 texcoord;
  vec2 overlay_coord;
  vec4 look_dir;
} fs_in;

layout (location=0) out vec4 color;


void main(void) {
  ivec3 size = textureSize(image, 0);
  uvec4 over_pixel = texture(overlay, fs_in.overlay_coord);
  vec3 direction = clamp(fs_in.look_dir.xyz, -1, 0);
  //vec3 limits = size + direction;  
  // ivec3 offset = -direction * int(round(fs_in.look_dir.xyz)) * size;
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
    vec3 base_coord = size * fs_in.texcoord.xyz;
    for (int i = slice[0]; i < slice[1]; i++) {
      // TODO The coordinate formula is complicated by the fact that the array index
      // must be [0, z) (where z is the current depth direction). Therefore just
      // multiplying by the size does not work correctly when counting down.
      // Try to figure out a better way.
      vec3 tex_coord = vec3(base_coord + (i + 0.5) * fs_in.look_dir.xyz);
      pixel = texelFetch(image, ivec3(floor(tex_coord)), 0);
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
