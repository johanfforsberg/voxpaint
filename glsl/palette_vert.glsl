#version 450 core


out VS_OUT {
  vec2 texcoord;
} vs_out;

void main(void) {
  const vec4 vertices[6] = vec4[6](vec4(-1, -1, 0, 1),
                                   vec4(1, -1, 0, 1),
                                   vec4(1, 1, 0, 1),

                                   vec4(-1, -1, 0, 1),
                                   vec4(1, 1, 0, 1),
                                   vec4(-1, 1, 0, 1));
  const vec2 texcoords[6] = vec2[6](vec2(0, 0),
                                    vec2(1, 0),
                                    vec2(1, 1),

                                    vec2(0, 0),
                                    vec2(1, 1),
                                    vec2(0, 1));
  gl_Position = vertices[gl_VertexID];
  vs_out.texcoord = texcoords[gl_VertexID];
}
