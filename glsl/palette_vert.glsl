#version 450 core

layout (location = 0) uniform mat4 view_matrix;
layout (location = 1) uniform vec3 look_dir;

out VS_OUT {
  vec4 texcoord;
  vec2 overlay_coord;
  vec4 look_dir;
} vs_out;

void main(void) {
  const vec4 vertices[6] = vec4[6](vec4(-1, -1, 0, 1),
                                   vec4(1, -1, 0, 1),
                                   vec4(1, 1, 0, 1),

                                   vec4(-1, -1, 0, 1),
                                   vec4(1, 1, 0, 1),
                                   vec4(-1, 1, 0, 1));
  const vec4 texcoords[6] = vec4[6](vec4(0, 0, 1, 1),
                                    vec4(1, 0, 1, 1),
                                    vec4(1, 1, 1, 1),

                                    vec4(0, 0, 1, 1),
                                    vec4(1, 1, 1, 1),
                                    vec4(0, 1, 1, 1));
  gl_Position = vertices[gl_VertexID];
  vs_out.texcoord = view_matrix * texcoords[gl_VertexID];
  vs_out.overlay_coord = texcoords[gl_VertexID].xy;
  vs_out.look_dir = vec4(-look_dir, 1);
  //vs_out.look_dir = vec4(0, 0, -1, 1);
}
