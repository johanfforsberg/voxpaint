#version 450 core

layout (location = 0) uniform mat4 view_matrix;

out VS_OUT {
  vec2 texcoord;
} vs_out;

void main(void) {
  const vec4 vertices[6] = vec4[6](vec4(-0.5, -0.5, 0, 1),
                                   vec4(0.5, -0.5, 0, 1),
                                   vec4(0.5, 0.5, 0, 1),

                                   vec4(-0.5, -0.5, 0, 1),
                                   vec4(0.5, 0.5, 0, 1),
                                   vec4(-0.5, 0.5, 0, 1));
  const vec2 texcoords[6] = vec2[6](vec2(0, 1),
                                    vec2(1, 1),
                                    vec2(1, 0),

                                    vec2(0, 1),
                                    vec2(1, 0),
                                    vec2(0, 0));
  gl_Position = view_matrix * vertices[gl_VertexID];
  vs_out.texcoord = texcoords[gl_VertexID];
}
