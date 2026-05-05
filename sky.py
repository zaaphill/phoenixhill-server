import math
from panda3d.core import (
    GeomVertexFormat, GeomVertexData, GeomVertexWriter,
    GeomTriangles, Geom, GeomNode, NodePath, Shader,
)
from direct.task import Task

# ── Tone-mapping shader ───────────────────────────────────────────────────────
# EXR stores linear HDR values (often >> 1).  Without this the bright sky
# areas clip to white.  Reinhard tone-maps to [0,1] then applies sRGB gamma.
_VERT = """
#version 140
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
in vec2 p3d_MultiTexCoord0;
out vec2 uv;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    uv = p3d_MultiTexCoord0;
}
"""

_FRAG = """
#version 140
uniform sampler2D p3d_Texture0;
uniform float exposure;
in vec2 uv;
out vec4 fragColor;
void main() {
    vec3 hdr = texture(p3d_Texture0, uv).rgb * exposure;
    // Luminance-based Reinhard — tone-maps brightness only, preserving hue/saturation
    float lum = dot(hdr, vec3(0.2126, 0.7152, 0.0722));
    float lum_mapped = lum / (lum + 1.0);
    vec3 ldr = hdr * (lum_mapped / max(lum, 0.0001));
    // Mild saturation boost — enough to make the blue pop without burning warm tones
    vec3 grey = vec3(dot(ldr, vec3(0.2126, 0.7152, 0.0722)));
    ldr = mix(grey, ldr, 1.3);
    // Slight blue push to keep the horizon from going grey
    ldr.b *= 1.08;
    // Linear -> sRGB gamma
    ldr = pow(clamp(ldr, 0.0, 1.0), vec3(1.0 / 2.2));
    fragColor = vec4(ldr, 1.0);
}
"""

# ── Sphere geometry ───────────────────────────────────────────────────────────
def _make_sky_sphere(stacks=32, slices=64):
    fmt   = GeomVertexFormat.getV3t2()
    vdata = GeomVertexData('sky_sphere', fmt, Geom.UHStatic)
    vw    = GeomVertexWriter(vdata, 'vertex')
    tw    = GeomVertexWriter(vdata, 'texcoord')

    for s in range(stacks + 1):
        phi = math.pi * s / stacks
        for r in range(slices + 1):
            theta = 2.0 * math.pi * r / slices
            x = math.sin(phi) * math.cos(theta)
            y = math.sin(phi) * math.sin(theta)
            z = math.cos(phi)
            vw.addData3(x, y, z)
            tw.addData2(r / slices, 1.0 - s / stacks)

    tris = GeomTriangles(Geom.UHStatic)
    for s in range(stacks):
        for r in range(slices):
            a = s * (slices + 1) + r
            b = a + 1
            c = a + (slices + 1)
            d = c + 1
            tris.addVertices(a, b, c)
            tris.addVertices(b, d, c)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode('sky_sphere')
    node.addGeom(geom)
    return NodePath(node)


# ── Mixin ─────────────────────────────────────────────────────────────────────
class SkyMixin:
    def setup_sky(self):
        tex = self.loader.loadTexture('citrus_orchard_puresky_4k.exr')

        self._sky = _make_sky_sphere()
        self._sky.setScale(500)
        self._sky.reparentTo(self.render)
        self._sky.setTexture(tex)
        self._sky.setLightOff()
        self._sky.setBin('background', -10)
        self._sky.setDepthWrite(False)

        sky_shader = Shader.make(Shader.SL_GLSL, _VERT, _FRAG)
        self._sky.setShader(sky_shader)
        self._sky.setShaderInput('exposure', 0.9)

        self.taskMgr.add(self._sky_follow_task, 'skyFollowTask')

    def _sky_follow_task(self, task):
        self._sky.setPos(self.camera.getPos(self.render))
        return Task.cont
