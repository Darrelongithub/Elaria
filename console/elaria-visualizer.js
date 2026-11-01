/*!
 * Elaria Living Intelligence Visualizer  v1.0
 * Needs THREE (r128+ UMD build) on window. No other dependencies.
 *
 *   const elaria = Elaria.create(document.getElementById('stage'));
 *   elaria.setState('listening');          // idle | listening | thinking | speaking | offline
 *   await elaria.useMicrophone();          // real microphone amplitude drives LISTENING
 *   await elaria.loadAudio(file);          // decoded audio file; elaria.playAudio() drives SPEAKING
 *   elaria.attachElement(audioEl);         // or hook your own TTS <audio>/<video> element
 *   elaria.attachStream(mediaStream);      // or a MediaStream (WebRTC, TTS stream)
 *   elaria.setLevels('output', {level});   // or push amplitude yourself (0..1, optional low/mid/high)
 *   elaria.simulate(true);                 // synthetic voice when no real signal is attached
 *   elaria.destroy();
 */
(function (global) {
  'use strict';

  /* ------------------------------------------------------------------ */
  /*  State table                                                        */
  /* ------------------------------------------------------------------ */
  var STATES = {
    idle:      { speed: 0.50, bright: 0.95, sat: 1.00, density: 0.55, alert: 0.0, inward: 0, contract: 0.00, weave: 0.15, glow: 0.50, react: 0.00, pulse: 0.40 },
    listening: { speed: 0.85, bright: 1.05, sat: 1.05, density: 0.85, alert: 1.0, inward: 0, contract: 0.00, weave: 0.25, glow: 0.70, react: 0.65, pulse: 0.55 },
    thinking:  { speed: 1.00, bright: 1.00, sat: 1.00, density: 0.80, alert: 0.2, inward: 1, contract: 0.55, weave: 1.00, glow: 1.00, react: 0.00, pulse: 0.00 },
    speaking:  { speed: 0.90, bright: 1.10, sat: 1.10, density: 1.00, alert: 0.5, inward: 0, contract: 0.00, weave: 0.50, glow: 0.80, react: 1.00, pulse: 0.65 },
    offline:   { speed: 0.10, bright: 0.30, sat: 0.30, density: 0.22, alert: 0.0, inward: 0, contract: 0.15, weave: 0.00, glow: 0.12, react: 0.00, pulse: 0.00 }
  };

  /* One dominant colour world per state. 9 stops, cycled and blended in the shaders. */
  function hx(h) { return [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255]; }
  var PALS = {
    idle:      ['#3b11a8', '#6a1fe0', '#9b2bff', '#2a3ad0', '#4a14c0', '#ff7a14', '#c23be0', '#7a2cff', '#3b11a8'].map(hx),
    listening: ['#1d3fff', '#2a6bff', '#18c8ff', '#3a68ff', '#6a3dff', '#18c8ff', '#1d3fff', '#8a3dff', '#2a6bff'].map(hx),
    thinking:  ['#ff2fb0', '#d41fff', '#ff5ac8', '#8a2cff', '#ff2fb0', '#ff8ad0', '#b01fff', '#ff2fb0', '#6a1fe0'].map(hx),
    speaking:  ['#ff6a00', '#ffb01a', '#ff3d6a', '#ff8a14', '#ffd23a', '#ff6a00', '#ff2fb0', '#ffa01a', '#ff6a00'].map(hx),
    offline:   ['#3a3552', '#4b4668', '#2e2a44', '#5a5575', '#3a3552', '#2e2a44', '#4b4668', '#3a3552', '#2e2a44'].map(hx)
  };
  var TAU = { speed: 0.8, bright: 0.9, sat: 0.9, density: 0.8, alert: 0.5, inward: 0.55, contract: 0.7, weave: 0.7, glow: 0.6, react: 0.3, pulse: 0.5 };

  /* ------------------------------------------------------------------ */
  /*  GLSL                                                               */
  /* ------------------------------------------------------------------ */
  var PAL = [
    'uniform vec3 uPal[9];',
    'const vec3 C_VIOLET  = vec3(0.23, 0.07, 0.66);',
    'const vec3 C_PURPLE  = vec3(0.61, 0.17, 1.00);',
    'const vec3 C_MAGENTA = vec3(1.00, 0.17, 0.72);',
    'const vec3 C_ORANGE  = vec3(1.00, 0.42, 0.02);',
    'const vec3 C_AMBER   = vec3(1.00, 0.70, 0.10);',
    'const vec3 C_COBALT  = vec3(0.12, 0.30, 1.00);',
    'const vec3 C_CYAN    = vec3(0.10, 0.85, 1.00);',
    'const vec3 C_PINK    = vec3(1.00, 0.56, 0.72);',
    'float h1(float n){ return fract(sin(n*127.1+17.3)*43758.5453); }',
    'vec3 stopC(int i){',
    '  if(i==0) return uPal[0];',
    '  if(i==1) return uPal[1];',
    '  if(i==2) return uPal[2];',
    '  if(i==3) return uPal[3];',
    '  if(i==4) return uPal[4];',
    '  if(i==5) return uPal[5];',
    '  if(i==6) return uPal[6];',
    '  if(i==7) return uPal[7];',
    '  return uPal[8];',
    '}',
    'vec3 pal(float x){',
    '  float xs = fract(x)*9.0;',
    '  float fi = floor(xs);',
    '  int i = int(fi);',
    '  int j = i + 1;',
    '  if(j > 8) j = 0;',
    '  float f = xs - fi;',
    '  f = f*f*(3.0-2.0*f);',
    '  return mix(stopC(i), stopC(j), f);',
    '}'
  ].join('\n');

  var VERT_COMMON = [
    'uniform float uTime;',
    'uniform float uFlow;',
    'uniform float uContract;',
    'uniform float uInterweave;',
    'uniform float uReact;',
    'uniform float uAmp;',
    'uniform float uLow;',
    'uniform float uHigh;',
    'uniform float uAlert;',
    'uniform float uBreath;',
    'uniform float uHist[16];',
    'uniform float uLayer;',
    'uniform mat3 uRot;',
    'float h1(float n){ return fract(sin(n*127.1+17.3)*43758.5453); }',
    'float histAt(float x){',
    '  x = clamp(x, 0.0, 14.999);',
    '  float f = floor(x);',
    '  float r0 = 0.0;',
    '  float r1 = 0.0;',
    '  for(int i=0;i<16;i++){',
    '    float fi = float(i);',
    '    if(fi == f) r0 = uHist[i];',
    '    if(fi == f + 1.0) r1 = uHist[i];',
    '  }',
    '  return mix(r0, r1, x - f);',
    '}',
    // Closed 3D curve: integer harmonics in u keep it seamless; time only shifts phases.
    'vec3 curvePos(float id, float u, float t){',
    '  float L = uLayer;',
    '  float a = u*6.2831853;',
    '  float s1 = h1(id*1.37+0.11);',
    '  float s2 = h1(id*2.71+1.70);',
    '  float s3 = h1(id*3.19+4.20);',
    '  float s4 = h1(id*5.31+9.10);',
    '  float s5 = h1(id*7.73+2.20);',
    '  float s6 = h1(id*11.1+6.60);',
    '  float fx = 1.0 + floor(s1*3.0) + L*(1.0+floor(s4*2.0));',
    '  float fy = 2.0 + floor(s2*3.0) + L*(1.0+floor(s5*2.0));',
    '  float fz = 1.0 + floor(s3*4.0) + L*(1.0+floor(s6*2.0));',
    '  float wv = 0.34 + 0.36*uInterweave;',
    '  vec3 p;',
    '  p.x = sin(fx*a + 6.2831853*s4 + t*(s2-0.5)*0.9)*(0.85+0.45*s5) + wv*sin((fx+2.0)*a + 6.2831853*s6 - t*(s1-0.5)*1.3);',
    '  p.y = sin(fy*a + 6.2831853*s5 + t*(s3-0.5)*0.8)*(0.70+0.50*s6) + wv*sin((fy+1.0)*a + 6.2831853*s1 + t*(s4-0.5)*1.1);',
    '  p.z = cos(fz*a + 6.2831853*s6 + t*(s1-0.5)*0.7)*(0.70+0.50*s4) + wv*sin((fz+3.0)*a + 6.2831853*s2 - t*(s5-0.5)*1.2);',
    '  vec3 d = normalize(p + vec3(0.0001));',
    // organic silhouette: radial distortion that drifts over time
    '  float n = sin(d.x*3.1 + t*0.31 + s1*6.0)*sin(d.y*2.7 - t*0.23 + s2*6.0) + 0.7*sin(d.z*3.9 + d.x*2.0 + t*0.27 + s3*6.0);',
    '  p *= 1.0 + 0.20*n;',
    '  p *= vec3(1.0 + 0.10*sin(t*0.17 + s1*6.0), 1.0 - 0.08*sin(t*0.13), 1.0);',
    // audio: each point along the ribbon reads an older slice of the amplitude history, so waves travel
    '  float tri = abs(fract(u + s3)*2.0 - 1.0);',
    '  float amp = histAt(0.5 + 12.0*tri);',
    '  float ripple = sin(a*7.0 - uFlow*2.4 + s2*6.2831853)*amp*uReact*0.16;',
    '  float scl = mix(1.0, 0.30, L)*mix(1.0, 0.70, uContract)*uBreath;',
    '  scl *= 1.0 + 0.05*uAlert + uReact*(0.30*amp + 0.10*uLow);',
    '  vec3 lean = vec3(0.18*sin(t*0.21+1.0), 0.12*sin(t*0.17+2.0), 0.08*sin(t*0.13))*(1.0 - 0.6*L);',
    '  p = p*scl + d*ripple*(1.0 - 0.5*L) + lean;',
    '  return uRot*p;',
    '}'
  ].join('\n');

  var RIBBON_VERT = VERT_COMMON + '\n' + [
    'attribute vec3 aRib;',
    'varying vec3 vR;',
    'varying vec3 vP;',
    'void main(){',
    '  float u = aRib.x;',
    '  float v = aRib.y;',
    '  float id = aRib.z;',
    '  float t = uTime;',
    '  float e = 0.003;',
    '  vec3 p0 = curvePos(id, u, t);',
    '  vec3 T = normalize(curvePos(id, u+e, t) - curvePos(id, u-e, t));',
    '  vec3 s0 = normalize(cross(T, normalize(vec3(0.31, 1.0, 0.22))));',
    '  float tws = 1.0 + floor(h1(id*4.1)*3.0);',
    '  float ang = u*6.2831853*tws + t*(h1(id*6.3)-0.5)*1.6 + uInterweave*1.5*sin(u*6.2831853*2.0 + id);',
    '  vec3 side = cos(ang)*s0 + sin(ang)*cross(T, s0);',
    '  float baseW = mix(0.10 + 0.16*h1(id*2.2), 0.014 + 0.022*h1(id*2.2), uLayer);',
    '  float w = baseW*(0.55 + 0.45*sin(u*6.2831853*3.0 + id*1.7 + t*0.5))*(1.0 + 0.30*uAlert + 0.5*uHigh*uReact);',
    '  vec3 pos = p0 + side*v*w;',
    '  vR = aRib;',
    '  vP = pos;',
    '  gl_Position = projectionMatrix*viewMatrix*vec4(pos, 1.0);',
    '}'
  ].join('\n');

  var RIBBON_FRAG = PAL + '\n' + [
    'uniform float uTime;',
    'uniform float uFlow;',
    'uniform float uBright;',
    'uniform float uSat;',
    'uniform float uCoreGlow;',
    'uniform float uInward;',
    'uniform float uAmp;',
    'uniform float uPulse;',
    'uniform float uPulseR;',
    'uniform float uWavePos;',
    'uniform vec3 uWaveDir;',
    'uniform float uLayer;',
    'varying vec3 vR;',
    'varying vec3 vP;',
    'void main(){',
    '  float u = vR.x;',
    '  float v = vR.y;',
    '  float id = vR.z;',
    '  float body = 0.30 + 0.70*(1.0 - smoothstep(0.35, 1.0, abs(v)));',
    '  float spine = exp(-pow(v*3.6, 2.0));',
    '  float fq = 2.0 + floor(h1(id*8.3)*4.0);',
    '  float flow = 0.5 + 0.5*sin(u*6.2831853*fq - uFlow*(0.8 + h1(id*3.3)) + id*2.0);',
    '  float stream = 0.12 + 0.88*pow(flow, 2.4);',
    '  float d = length(vP);',
    '  float coreB = uCoreGlow*exp(-d*d*0.8);',
    '  float inwardW = uInward*pow(0.5 + 0.5*sin(d*5.5 + uFlow*2.0), 3.0)*exp(-d*0.5);',
    '  float pulse = uPulse*exp(-pow(d - uPulseR, 2.0)*10.0);',
    '  float hue = u*0.55 + id*0.113 + uTime*0.02;',
    '  hue += 0.38*exp(-pow(dot(vP, uWaveDir) - uWavePos, 2.0)*0.9);',
    '  vec3 col = pal(hue);',
    '  float acc = smoothstep(0.90, 1.0, 0.5 + 0.5*sin(u*41.0 + id*5.0 + uFlow*0.6));',
    '  col = mix(col, C_CYAN, acc*0.55);',
    '  float pk = smoothstep(0.95, 1.0, 0.5 + 0.5*sin(u*29.0 - id*3.0 - uFlow*0.9));',
    '  col = mix(col, C_PINK, pk*0.5);',
    '  float depthF = mix(0.55, 1.0, smoothstep(-1.6, 1.6, vP.z));',
    '  float lay = mix(1.0, 1.4, uLayer);',
    '  float a = (body*stream*(0.42 + 0.9*coreB + 1.4*inwardW + 2.0*pulse + 0.7*uAmp) + spine*0.45*flow)*depthF*lay*0.55;',
    '  a = clamp(a*uBright, 0.0, 0.85);',
    '  float g = dot(col, vec3(0.299, 0.587, 0.114));',
    '  col = mix(vec3(g), col, uSat);',
    '  col = mix(col, vec3(0.22, 0.20, 0.34), (1.0 - clamp(uSat, 0.0, 1.0))*0.35);',
    '  gl_FragColor = vec4(col*a, a*0.9);',
    '}'
  ].join('\n');

  var POINT_VERT = VERT_COMMON + '\n' + [
    'attribute vec4 aSeed;',
    'uniform float uNRib;',
    'uniform float uIdBase;',
    'uniform float uDensity;',
    'uniform float uSizeScale;',
    'uniform float uDist;',
    'uniform float uInward;',
    'uniform float uWavePos;',
    'uniform vec3 uWaveDir;',
    'varying float vHue;',
    'varying float vAlpha;',
    'varying float vSpark;',
    'void main(){',
    '  float rnd = h1(aSeed.x*91.7 + aSeed.y*13.1 + aSeed.w*7.7);',
    '  float vis = 1.0 - smoothstep(uDensity - 0.08, uDensity, rnd);',
    '  float id = uIdBase + floor(aSeed.x*uNRib);',
    '  float dirn = aSeed.w > 0.5 ? 1.0 : -1.0;',
    '  float u = fract(aSeed.y + uFlow*(0.02 + 0.07*aSeed.z)*dirn);',
    '  vec3 p;',
    '  if(uLayer < 1.5){',
    '    p = curvePos(id, u, uTime);',
    '    vec3 jit = vec3(h1(aSeed.z*37.0), h1(aSeed.x*53.0 + 1.0), h1(aSeed.y*71.0 + 2.0)) - 0.5;',
    '    float sc = (0.05 + 0.20*aSeed.w)*mix(1.0, 0.35, uLayer);',
    '    p += jit*sc*(1.0 + 0.6*sin(uTime*0.8 + aSeed.z*20.0));',
    '  } else {',
    '    float ph = aSeed.x*6.2831853*3.0;',
    '    float th = acos(2.0*aSeed.y - 1.0);',
    '    float rr = 0.9 + 1.5*aSeed.z;',
    '    vec3 d0 = vec3(sin(th)*cos(ph), 0.8*cos(th), sin(th)*sin(ph));',
    '    float sw = uFlow*0.03*(aSeed.w - 0.5)*2.0 + aSeed.x*10.0;',
    '    float cs = cos(sw);',
    '    float sn = sin(sw);',
    '    d0 = vec3(cs*d0.x + sn*d0.z, d0.y + 0.1*sin(uTime*0.5 + aSeed.z*30.0), -sn*d0.x + cs*d0.z);',
    '    p = uRot*(d0*rr*(0.8 + 0.2*sin(uTime*0.3 + aSeed.y*20.0))*uBreath);',
    '  }',
    '  float life = fract(aSeed.z*7.0 + uFlow*0.12);',
    '  float lifeFade = smoothstep(0.0, 0.1, life)*(1.0 - smoothstep(0.88, 1.0, life));',
    '  p *= 1.0 - uInward*0.88*pow(life, 1.4);',
    '  vec4 mv = viewMatrix*vec4(p, 1.0);',
    '  gl_Position = projectionMatrix*mv;',
    '  float sz = 1.2 + 3.2*pow(0.5*aSeed.z + 0.5*h1(aSeed.w*19.0), 3.0);',
    '  gl_PointSize = max(1.0, sz*uSizeScale*(uDist/(-mv.z))*(1.0 + 0.5*uAmp*uReact));',
    '  float baseA = 0.30 + 0.70*h1(aSeed.z*44.0 + aSeed.x);',
    '  float dustK = uLayer > 1.5 ? 0.45 : 1.0;',
    '  vAlpha = vis*baseA*dustK*mix(1.0, lifeFade, uInward);',
    '  vSpark = h1(aSeed.x*17.0 + aSeed.z*5.0);',
    '  vHue = aSeed.y*0.6 + id*0.113 + uTime*0.02 + 0.38*exp(-pow(dot(p, uWaveDir) - uWavePos, 2.0)*0.9);',
    '}'
  ].join('\n');

  var POINT_FRAG = PAL + '\n' + [
    'uniform float uBright;',
    'uniform float uSat;',
    'varying float vHue;',
    'varying float vAlpha;',
    'varying float vSpark;',
    'void main(){',
    '  vec2 c = gl_PointCoord - 0.5;',
    '  float r = length(c)*2.0;',
    '  if(r > 1.0) discard;',
    '  float soft = exp(-r*r*3.4);',
    '  float a = clamp(soft*vAlpha*uBright, 0.0, 1.0);',
    '  vec3 col = pal(vHue);',
    '  float acc = step(0.93, fract(vSpark*7.31));',
    '  col = mix(col, C_CYAN, acc*0.6);',
    // white only as a few tiny highlights
    '  float spark = step(0.975, vSpark);',
    '  col = mix(col, vec3(1.0, 0.96, 0.92), spark*0.8*smoothstep(0.7, 0.0, r));',
    '  float g = dot(col, vec3(0.299, 0.587, 0.114));',
    '  col = mix(vec3(g), col, uSat);',
    '  gl_FragColor = vec4(col*a, a*0.75);',
    '}'
  ].join('\n');

  var HAZE_VERT = [
    'varying vec2 vUv;',
    'void main(){',
    '  vUv = uv;',
    '  gl_Position = vec4(position.xy, 0.0, 1.0);',
    '}'
  ].join('\n');

  var HAZE_FRAG = PAL + '\n' + [
    'uniform vec2 uScaleP;',
    'uniform float uTime;',
    'uniform float uBright;',
    'uniform float uSat;',
    'uniform float uAmp;',
    'uniform float uCoreGlow;',
    'varying vec2 vUv;',
    'float hash2(vec2 p){ p = fract(p*vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x*p.y); }',
    'float vnoise(vec2 p){',
    '  vec2 i = floor(p);',
    '  vec2 f = fract(p);',
    '  f = f*f*(3.0 - 2.0*f);',
    '  float a = hash2(i);',
    '  float b = hash2(i + vec2(1.0, 0.0));',
    '  float c = hash2(i + vec2(0.0, 1.0));',
    '  float d = hash2(i + vec2(1.0, 1.0));',
    '  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);',
    '}',
    'float fbm(vec2 p){',
    '  float s = 0.0;',
    '  float a = 0.5;',
    '  for(int i=0;i<4;i++){ s += a*vnoise(p); p = p*2.03 + vec2(17.1, 9.7); a *= 0.5; }',
    '  return s;',
    '}',
    'void main(){',
    '  vec2 p = (vUv*2.0 - 1.0)*uScaleP;',
    '  float t = uTime*0.35;',
    '  vec2 q = p*0.9;',
    '  vec2 w = vec2(fbm(q + vec2(0.0, t)), fbm(q + vec2(5.2, 1.3) - t*0.8));',
    '  float n = fbm(q + 2.2*w + vec2(t*0.5));',
    // thin flowing veins along two noise contours instead of a flat gradient
    '  float vein = exp(-pow((n - 0.52)*10.0, 2.0)) + 0.6*exp(-pow((n - 0.40)*12.0, 2.0));',
    '  float r = length(p*vec2(0.95, 1.08));',
    '  float ang = atan(p.y, p.x);',
    '  float rad = 1.15 + 0.28*sin(ang*2.0 + t*1.7) + 0.20*sin(ang*3.0 - t*1.1 + 1.0) + 0.5*(n - 0.5);',
    '  float env = exp(-pow(r/rad, 2.4)*1.6);',
    '  vec3 col = pal(n*0.9 + ang*0.08 + uTime*0.02 + 0.25*w.x);',
    '  float a = env*(0.04 + 0.26*vein + 0.08*n)*(0.7 + 0.5*uCoreGlow + 0.4*uAmp);',
    '  a = clamp(a*uBright, 0.0, 0.5);',
    '  float g = dot(col, vec3(0.299, 0.587, 0.114));',
    '  col = mix(vec3(g), col, uSat);',
    '  gl_FragColor = vec4(col*a, a*0.7);',
    '}'
  ].join('\n');

  /* ------------------------------------------------------------------ */
  /*  Helpers                                                            */
  /* ------------------------------------------------------------------ */
  function damp(c, t, tau, dt) { return c + (t - c) * (1 - Math.exp(-dt / tau)); }
  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
  function smooth01(x) { x = clamp01(x); return x * x * (3 - 2 * x); }
  var ZERO = { level: 0, low: 0, mid: 0, high: 0 };

  function ribbonGeometry(THREE, count, segs, idBase) {
    var vCount = count * 2 * (segs + 1);
    var aRib = new Float32Array(vCount * 3);
    var pos = new Float32Array(vCount * 3);
    var idx = vCount < 65535 ? new Uint16Array(count * segs * 6) : new Uint32Array(count * segs * 6);
    var vi = 0, ii = 0;
    for (var r = 0; r < count; r++) {
      var base = vi;
      for (var s = 0; s <= segs; s++) {
        var u = s / segs;
        for (var k = 0; k < 2; k++) {
          aRib[vi * 3] = u; aRib[vi * 3 + 1] = k ? 1 : -1; aRib[vi * 3 + 2] = idBase + r; vi++;
        }
      }
      for (var s2 = 0; s2 < segs; s2++) {
        var a = base + s2 * 2, b = a + 1, c = a + 2, d = a + 3;
        idx[ii++] = a; idx[ii++] = b; idx[ii++] = c; idx[ii++] = b; idx[ii++] = d; idx[ii++] = c;
      }
    }
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aRib', new THREE.BufferAttribute(aRib, 3));
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    return g;
  }

  function pointGeometry(THREE, n) {
    var g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    var s = new Float32Array(n * 4);
    for (var i = 0; i < s.length; i++) s[i] = Math.random();
    g.setAttribute('aSeed', new THREE.BufferAttribute(s, 4));
    return g;
  }

  /* ------------------------------------------------------------------ */
  /*  create()                                                           */
  /* ------------------------------------------------------------------ */
  function create(container, opts) {
    opts = opts || {};
    var THREE = global.THREE;
    if (!THREE) throw new Error('Elaria: three.js must be loaded before the visualizer.');

    var reduced = !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
    var renderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: false, premultipliedAlpha: true, powerPreference: 'high-performance' });
    } catch (err) {
      throw new Error('Elaria: WebGL is not available in this browser.');
    }
    renderer.setClearColor(0x000000, 0);
    var canvas = renderer.domElement;
    canvas.style.cssText = 'display:block;width:100%;height:100%;background:transparent';
    if (global.getComputedStyle(container).position === 'static') container.style.position = 'relative';
    container.appendChild(canvas);

    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(38, 1, 0.1, 60);
    var FIT_R = opts.fit || 2.3; // smaller = structure fills more of the panel (try 1.8 for a narrow side panel)

    // ---- shared uniforms ------------------------------------------------
    var hist = new Float32Array(16);
    var U = {
      uTime: { value: 0 }, uFlow: { value: 0 }, uBright: { value: 1 }, uSat: { value: 1 },
      uCoreGlow: { value: 0.5 }, uInward: { value: 0 }, uContract: { value: 0 }, uInterweave: { value: 0.2 },
      uReact: { value: 0 }, uAmp: { value: 0 }, uLow: { value: 0 }, uMid: { value: 0 }, uHigh: { value: 0 },
      uAlert: { value: 0 }, uBreath: { value: 1 }, uHist: { value: hist },
      uPal: { value: PALS.idle.map(function (c) { return new THREE.Vector3(c[0], c[1], c[2]); }) },
      uWavePos: { value: 99 }, uWaveDir: { value: new THREE.Vector3(1, 0, 0) },
      uPulse: { value: 0 }, uPulseR: { value: 0 },
      uSizeScale: { value: 1 }, uDist: { value: 7 }, uScaleP: { value: new THREE.Vector2(FIT_R, FIT_R) }
    };

    function material(vs, fs, extra) {
      return new THREE.ShaderMaterial({
        vertexShader: vs, fragmentShader: fs, uniforms: Object.assign({}, U, extra),
        transparent: true, depthTest: false, depthWrite: false, side: THREE.DoubleSide,
        blending: THREE.CustomBlending, blendEquation: THREE.AddEquation,
        blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor
      });
    }

    var rotOuter = new THREE.Matrix3();
    var rotCore = new THREE.Matrix3();
    var N_OUT = 12, N_CORE = 26;

    var hazeMat = material(HAZE_VERT, HAZE_FRAG, {});
    var haze = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), hazeMat);
    haze.frustumCulled = false; haze.renderOrder = -10;
    scene.add(haze);

    var objects = [];
    function add(obj, order) { obj.frustumCulled = false; obj.renderOrder = order; scene.add(obj); objects.push(obj); return obj; }

    var dustMat = material(POINT_VERT, POINT_FRAG, { uLayer: { value: 2 }, uRot: { value: rotOuter }, uNRib: { value: 1 }, uIdBase: { value: 1 }, uDensity: { value: 0.5 } });
    add(new THREE.Points(pointGeometry(THREE, 900), dustMat), -5);

    var ribOutMat = material(RIBBON_VERT, RIBBON_FRAG, { uLayer: { value: 0 }, uRot: { value: rotOuter } });
    add(new THREE.Mesh(ribbonGeometry(THREE, N_OUT, 420, 1), ribOutMat), 0);

    var ribCoreMat = material(RIBBON_VERT, RIBBON_FRAG, { uLayer: { value: 1 }, uRot: { value: rotCore } });
    add(new THREE.Mesh(ribbonGeometry(THREE, N_CORE, 520, 40), ribCoreMat), 1);

    var ptOutMat = material(POINT_VERT, POINT_FRAG, { uLayer: { value: 0 }, uRot: { value: rotOuter }, uNRib: { value: N_OUT }, uIdBase: { value: 1 }, uDensity: { value: 0.5 } });
    add(new THREE.Points(pointGeometry(THREE, 5000), ptOutMat), 2);

    var ptCoreMat = material(POINT_VERT, POINT_FRAG, { uLayer: { value: 1 }, uRot: { value: rotCore }, uNRib: { value: N_CORE }, uIdBase: { value: 40 }, uDensity: { value: 0.5 } });
    add(new THREE.Points(pointGeometry(THREE, 2200), ptCoreMat), 3);

    // ---- state ----------------------------------------------------------
    var state = 'idle';
    var tgt = Object.assign({}, STATES.idle);
    var tgtPal = PALS.idle;
    var cur = Object.assign({}, STATES.idle);
    var listeners = { state: [] };
    var morph = 0, flow = 0, rotClock = 0;
    var amp = 0, ampSlow = 0, low = 0, mid = 0, high = 0, histT = 0;
    var pulse = { on: false, t: 0, dur: 1.8, str: 0, dir: 1 };
    var nextAuto = 1.2, nextWave = 5, wave = { on: false, t: 0 };
    var cooldown = 0;
    var info = { state: state, role: null, source: 'none', level: 0, low: 0, mid: 0, high: 0 };

    function emit(name, a) { (listeners[name] || []).slice().forEach(function (fn) { try { fn(a); } catch (e) { /* host handler error */ } }); }

    function triggerPulse(str, dir, dur) {
      pulse.on = true; pulse.t = 0; pulse.str = str; pulse.dir = dir || 1; pulse.dur = dur || 1.8;
    }

    function setState(name) {
      if (!STATES[name]) throw new Error('Elaria: unknown state "' + name + '". Use idle, listening, thinking, speaking or offline.');
      if (name === state) return;
      state = name;
      tgt = Object.assign({}, STATES[name]);
      tgtPal = PALS[name];
      nextAuto = name === 'thinking' ? 0.1 : 0.6;
      if (name === 'listening' || name === 'speaking') triggerPulse(0.7, 1, 1.6);
      emit('state', name);
    }

    // ---- audio ----------------------------------------------------------
    var actx = null, inAn = null, outAn = null;
    var micStream = null, micNode = null, outNode = null, elNode = null, streamNode = null, elSource = null;
    var audioBuf = null, bufSrc = null;
    var simOn = !!opts.simulate;
    var src = { input: { live: false, ext: null }, output: { live: false, ext: null } };
    var fdIn, tdIn, fdOut, tdOut;

    function makeAnalyser() {
      var a = actx.createAnalyser();
      a.fftSize = 1024; a.smoothingTimeConstant = 0.5;
      return a;
    }
    function ensureAudio() {
      if (!actx) {
        var AC = global.AudioContext || global.webkitAudioContext;
        if (!AC) throw new Error('Web Audio is not supported in this browser.');
        actx = new AC();
        inAn = makeAnalyser(); outAn = makeAnalyser();
        fdIn = new Uint8Array(inAn.frequencyBinCount); tdIn = new Uint8Array(inAn.fftSize);
        fdOut = new Uint8Array(outAn.frequencyBinCount); tdOut = new Uint8Array(outAn.fftSize);
      }
      if (actx.state === 'suspended' && actx.resume) actx.resume();
    }

    function analyse(an, fd, td) {
      an.getByteTimeDomainData(td);
      var sum = 0, i;
      for (i = 0; i < td.length; i++) { var v = (td[i] - 128) / 128; sum += v * v; }
      var rms = Math.sqrt(sum / td.length);
      an.getByteFrequencyData(fd);
      function band(a, b, gain) { var s = 0; for (var k = a; k <= b; k++) s += fd[k]; return clamp01((s / (b - a + 1)) / 255 * gain); }
      return { level: clamp01(Math.pow(rms * 4.2, 0.7)), low: band(1, 6, 1.6), mid: band(7, 40, 2.0), high: band(41, 180, 3.2) };
    }

    function synth(role, t) {
      var tt = t + (role === 'input' ? 0 : 3.7);
      var gate = smooth01((Math.sin(tt * 0.8) + 0.55 * Math.sin(tt * 1.93 + 1.1) + 0.2) * 1.6);
      var syl = Math.pow(Math.max(0, Math.sin(tt * 2 * Math.PI * (role === 'input' ? 2.6 : 3.5) + 1.4 * Math.sin(tt * 0.7))), 1.4);
      var lvl = clamp01(gate * (0.25 + 0.75 * syl) * (0.7 + 0.3 * Math.sin(tt * 1.7)));
      return { level: lvl, low: lvl * (0.65 + 0.35 * Math.sin(tt * 2.3)), mid: lvl * (0.55 + 0.45 * Math.sin(tt * 3.1 + 1)), high: lvl * Math.max(0, Math.sin(tt * 9.7)) * 0.9 };
    }

    // returns { sample, source }
    function sampleRole(role, t) {
      var s = src[role];
      if (s.live && actx) {
        return { sample: role === 'input' ? analyse(inAn, fdIn, tdIn) : analyse(outAn, fdOut, tdOut), source: 'live' };
      }
      if (s.ext && s.ext.until > Date.now()) return { sample: s.ext.v, source: 'external' };
      if (simOn) return { sample: synth(role, t), source: 'simulated' };
      return { sample: ZERO, source: 'none' };
    }

    function releaseMicrophone() {
      if (micStream) { micStream.getTracks().forEach(function (tr) { tr.stop(); }); micStream = null; }
      if (micNode) { try { micNode.disconnect(); } catch (e) { /* already gone */ } micNode = null; }
      src.input.live = false;
    }

    function useMicrophone() {
      if (!global.navigator || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        return Promise.reject(new Error('This browser has no microphone API.'));
      }
      try { ensureAudio(); } catch (e) { return Promise.reject(e); }
      return navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false }, video: false }).then(function (stream) {
        releaseMicrophone();
        micStream = stream;
        micNode = actx.createMediaStreamSource(stream);
        micNode.connect(inAn);
        src.input.live = true;
      });
    }

    function stopAudio() {
      if (bufSrc) { try { bufSrc.onended = null; bufSrc.stop(); } catch (e) { /* not started */ } try { bufSrc.disconnect(); } catch (e2) { /* already gone */ } bufSrc = null; }
      if (!elNode && !streamNode) src.output.live = false;
    }

    function loadAudio(input) {
      try { ensureAudio(); } catch (e) { return Promise.reject(e); }
      var p = (input && input.arrayBuffer) ? input.arrayBuffer() : Promise.resolve(input.slice(0));
      return p.then(function (ab) {
        return new Promise(function (res, rej) { actx.decodeAudioData(ab, res, rej); });
      }).then(function (buf) { audioBuf = buf; return buf.duration; });
    }

    function playAudio(o) {
      if (!audioBuf) throw new Error('Elaria: load an audio file first with loadAudio().');
      ensureAudio(); stopAudio();
      var s = actx.createBufferSource();
      s.buffer = audioBuf; s.loop = !o || o.loop !== false;
      s.connect(outAn); s.connect(actx.destination);
      s.onended = function () { if (bufSrc === s) { bufSrc = null; src.output.live = false; } };
      s.start();
      bufSrc = s; src.output.live = true;
    }

    function attachElement(el) {
      ensureAudio();
      if (elSource !== el) {
        if (elNode) { try { elNode.disconnect(); } catch (e) { /* already gone */ } }
        elNode = actx.createMediaElementSource(el);
        elSource = el;
      }
      elNode.connect(outAn); elNode.connect(actx.destination);
      src.output.live = true;
    }

    function attachStream(stream, role) {
      ensureAudio();
      var node = actx.createMediaStreamSource(stream);
      if (role === 'input') { node.connect(inAn); src.input.live = true; }
      else { if (streamNode) { try { streamNode.disconnect(); } catch (e) { /* already gone */ } } streamNode = node; node.connect(outAn); src.output.live = true; }
    }

    function setLevels(role, v) {
      var r = role === 'input' ? 'input' : 'output';
      var l = clamp01(+v.level || 0);
      src[r].ext = { until: Date.now() + 500, v: { level: l, low: clamp01(v.low == null ? l : v.low), mid: clamp01(v.mid == null ? l : v.mid), high: clamp01(v.high == null ? l * 0.6 : v.high) } };
    }

    // ---- sizing ---------------------------------------------------------
    var pr = Math.min(global.devicePixelRatio || 1, opts.maxPixelRatio || 2);
    var W = 1, H = 1;
    function resize() {
      W = Math.max(1, container.clientWidth); H = Math.max(1, container.clientHeight);
      renderer.setPixelRatio(pr); renderer.setSize(W, H, false);
      var aspect = W / H;
      camera.aspect = aspect;
      var tf = Math.tan(camera.fov * Math.PI / 360);
      var dist = FIT_R / (tf * Math.min(1, aspect));
      camera.position.set(0, 0, dist); camera.updateProjectionMatrix();
      U.uDist.value = dist;
      U.uSizeScale.value = Math.min(W, H) * pr / 800;
      U.uScaleP.value.set(Math.max(aspect, 1) * FIT_R, Math.max(1 / aspect, 1) * FIT_R);
    }
    var ro = null;
    if (global.ResizeObserver) { ro = new ResizeObserver(resize); ro.observe(container); }
    else global.addEventListener('resize', resize);
    resize();

    // ---- frame ----------------------------------------------------------
    var eul = new THREE.Euler(), m4 = new THREE.Matrix4();
    var raf = 0, last = 0, running = false, visible = true, acc = 0, accN = 0;

    function step(dt, wall) {
      var k;
      for (k in TAU) cur[k] = damp(cur[k], tgt[k], TAU[k], dt);
      for (var pi = 0; pi < 9; pi++) {
        var pv = U.uPal.value[pi], pt = tgtPal[pi];
        pv.x = damp(pv.x, pt[0], 0.6, dt); pv.y = damp(pv.y, pt[1], 0.6, dt); pv.z = damp(pv.z, pt[2], 0.6, dt);
      }
      var sp = cur.speed * (reduced ? 0.5 : 1);
      morph += dt * (0.12 + 1.5 * sp);
      flow += dt * (0.2 + 3.0 * sp);
      rotClock += dt * (0.12 + 0.9 * sp);
      U.uTime.value = morph; U.uFlow.value = flow;
      U.uBright.value = cur.bright; U.uSat.value = cur.sat; U.uCoreGlow.value = cur.glow;
      U.uInward.value = cur.inward; U.uContract.value = cur.contract; U.uInterweave.value = cur.weave;
      U.uReact.value = cur.react; U.uAlert.value = cur.alert;
      ptOutMat.uniforms.uDensity.value = cur.density;
      ptCoreMat.uniforms.uDensity.value = cur.density * 0.9;
      dustMat.uniforms.uDensity.value = cur.density * 0.55;

      // audio -> amplitude
      var role = state === 'listening' ? 'input' : state === 'speaking' ? 'output' : null;
      var res = role ? sampleRole(role, wall) : { sample: ZERO, source: 'none' };
      var s = res.sample;
      var kA = 1 - Math.exp(-dt / (s.level > amp ? 0.035 : 0.16));
      amp += (s.level - amp) * kA;
      low += (s.low - low) * kA; mid += (s.mid - mid) * kA; high += (s.high - high) * kA;
      ampSlow = damp(ampSlow, amp, 0.25, dt);
      U.uAmp.value = amp; U.uLow.value = low; U.uMid.value = mid; U.uHigh.value = high;
      histT += dt;
      while (histT >= 0.05) { histT -= 0.05; hist.copyWithin(1, 0, 15); hist[0] = amp; }
      info.state = state; info.role = role; info.source = res.source;
      info.level = amp; info.low = low; info.mid = mid; info.high = high;

      // pulses
      cooldown -= dt;
      if (cur.react > 0.3 && amp - ampSlow > 0.16 && cooldown <= 0) { triggerPulse(0.5 + 0.5 * amp, 1, 1.4); cooldown = 0.35; }
      nextAuto -= dt;
      if (nextAuto <= 0 && !pulse.on) {
        if (state === 'thinking') { triggerPulse(0.9, -1, 1.3); nextAuto = 0.5 + Math.random() * 0.9; }
        else if (cur.pulse > 0.05) { triggerPulse(cur.pulse, 1, 2.4); nextAuto = 2.5 + Math.random() * 3.5; }
        else nextAuto = 1;
      }
      if (pulse.on) {
        pulse.t += dt;
        var kp = pulse.t / pulse.dur;
        var kk = Math.min(kp, 1);
        U.uPulseR.value = pulse.dir > 0 ? 0.2 + kk * 2.4 : 2.6 - kk * 2.4;
        U.uPulse.value = pulse.str * Math.sin(Math.PI * kk);
        if (kp >= 1) { pulse.on = false; U.uPulse.value = 0; }
      }

      // travelling colour wave
      if (state !== 'offline') {
        if (wave.on) {
          wave.t += dt;
          var kw = wave.t / 3.4;
          U.uWavePos.value = -3 + kw * 6;
          if (kw >= 1) { wave.on = false; U.uWavePos.value = 99; nextWave = 10 + Math.random() * 8; }
        } else {
          nextWave -= dt;
          if (nextWave <= 0 && !reduced) {
            wave.on = true; wave.t = 0;
            U.uWaveDir.value.set(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize();
          }
        }
      }

      U.uBreath.value = 1 + 0.04 * Math.sin(morph * 0.55) + 0.025 * Math.sin(morph * 1.07 + 1.3) + 0.012 * Math.sin(morph * 2.3);

      // independent, irregular layer rotation
      var t = rotClock;
      eul.set(0.35 * Math.sin(t * 0.11) + 0.18 * Math.sin(t * 0.23 + 1.3), t * 0.07 + 0.4 * Math.sin(t * 0.09), 0.25 * Math.sin(t * 0.05 + 2.0));
      m4.makeRotationFromEuler(eul); rotOuter.setFromMatrix4(m4);
      eul.set(-0.5 * Math.sin(t * 0.17 + 0.6), -t * 0.11 + 0.5 * Math.sin(t * 0.13 + 1.0), 0.4 * Math.sin(t * 0.09));
      m4.makeRotationFromEuler(eul); rotCore.setFromMatrix4(m4);
    }

    function frame(now) {
      raf = global.requestAnimationFrame(frame);
      var dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016);
      last = now;
      step(dt, now / 1000);
      renderer.render(scene, camera);
      // drop resolution if the device cannot hold ~40fps
      acc += dt; accN++;
      if (accN >= 90) {
        if (acc / accN > 0.026 && pr > 1) { pr = Math.max(1, pr - 0.25); resize(); }
        acc = 0; accN = 0;
      }
    }
    function start() { if (!running && visible && !document.hidden) { running = true; last = 0; raf = global.requestAnimationFrame(frame); } }
    function stop() { if (running) { global.cancelAnimationFrame(raf); running = false; } }
    function onVis() { if (document.hidden) stop(); else start(); }
    document.addEventListener('visibilitychange', onVis);
    var io = null;
    if (global.IntersectionObserver) {
      io = new IntersectionObserver(function (e) { visible = e[0].isIntersecting; if (visible) start(); else stop(); });
      io.observe(container);
    }
    // settle the first still frame instantly, then animate
    for (var i = 0; i < 24; i++) step(0.05, i * 0.05);
    start();

    return {
      canvas: canvas,
      states: Object.keys(STATES),
      setState: setState,
      getState: function () { return state; },
      getLevels: function () { return { state: info.state, role: info.role, source: info.source, level: info.level, low: info.low, mid: info.mid, high: info.high }; },
      on: function (name, fn) { (listeners[name] = listeners[name] || []).push(fn); },
      useMicrophone: useMicrophone,
      releaseMicrophone: releaseMicrophone,
      loadAudio: loadAudio,
      hasAudio: function () { return !!audioBuf; },
      playAudio: playAudio,
      stopAudio: stopAudio,
      attachElement: attachElement,
      attachStream: attachStream,
      setLevels: setLevels,
      simulate: function (on) { simOn = !!on; },
      isSimulating: function () { return simOn; },
      destroy: function () {
        stop();
        document.removeEventListener('visibilitychange', onVis);
        if (ro) ro.disconnect(); else global.removeEventListener('resize', resize);
        if (io) io.disconnect();
        stopAudio(); releaseMicrophone();
        if (actx && actx.close) { try { actx.close(); } catch (e) { /* already closed */ } }
        objects.concat([haze]).forEach(function (o) { o.geometry.dispose(); o.material.dispose(); });
        renderer.dispose();
        if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
      }
    };
  }

  global.Elaria = { create: create, states: Object.keys(STATES), version: '1.0.0' };
})(typeof window !== 'undefined' ? window : this);
