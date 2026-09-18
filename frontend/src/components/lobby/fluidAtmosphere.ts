import * as THREE from "three";
import { FluidSimulation } from "three-fluid-fx";
import { FrameBudget } from "./frameBudget";
import { sampleRevealPath, type RevealPoint } from "./revealPath";

const vertexShader = `
varying vec2 vUv;
void main() { vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }
`;
const fragmentShader = `
uniform sampler2D map, density, velocity, dye, detailMap;
uniform vec2 viewport, imageSize, detailSize, panelSize, origin;
uniform vec4 rect;
uniform float time, reveal, isCard, surfaceOpacity, ambientWave, detailReady;
uniform vec2 ambientOrigin;
varying vec2 vUv;
float noise(vec2 p) {
  return .5+.25*sin(p.x*7.1+sin(p.y*8.2+time*.55))+.25*cos(p.y*10.3+sin(p.x*5.4-time*.37));
}
float hash(vec2 p) { return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453); }
float valueNoise(vec2 p) {
  vec2 i=floor(p), f=fract(p); f=f*f*(3.-2.*f);
  return mix(mix(hash(i),hash(i+vec2(1.,0.)),f.x),mix(hash(i+vec2(0.,1.)),hash(i+1.),f.x),f.y);
}
float brushGrain(vec2 p) {
  return valueNoise(p)*.57+valueNoise(p*2.07+13.4)*.28+valueNoise(p*4.19+7.2)*.15;
}
void main() {
  if(isCard>.5 && vUv.y>.5) {
    vec2 corner=abs((vUv-.5)*panelSize)-panelSize*.5+vec2(12.);
    if(length(max(corner,0.))>12.) discard;
  }
  vec2 screen=(rect.xy+vUv*rect.zw)/viewport;
  vec2 flow=texture2D(velocity,screen).xy;
  vec3 pigment=texture2D(density,screen).rgb;
  float ink=1.-exp(-pigment.b*.75);
  // Only autonomous sources write blue density. XY also carry solver velocity.
  float paint=1.-exp(-pigment.b*1.71);
  float grain=.5, fold=.5, pearlescence=0.;
  // Most of the viewport contains no dye; do not evaluate its marble field.
  if(max(ink,paint)>.00001) {
    grain=noise(screen*5.+flow*.018);
    vec2 marbleUv=screen*vec2(viewport.x/viewport.y,1.)*6.;
    vec2 drift=clamp(flow*.008,vec2(-.18),vec2(.18));
    fold=noise(marbleUv+drift+vec2(grain*.7,grain*.35));
    float veins=pow(1.-abs(sin(fold*12.+grain*2.)),4.);
    pearlescence=paint*.65*(veins*.7+fold*.2);
  }

  // Reveal the fixed artwork through a short-lived, eroding brush mask. Texture
  // detail comes from the palace itself, never from a light drawn over it.
  float unveiling=0.;
  vec2 present=texture2D(dye,screen).rg;
  if(max(present.r,present.g)>.012 && !(isCard>.5 && reveal>.995)) {
    vec2 pixels=screen*viewport;
    vec2 brushUv=pixels/48.+vec2(time*.045,-time*.03);
    float edgeGrain=brushGrain(brushUv);
    vec2 driftPx=clamp(flow*.18,vec2(-4.),vec2(4.));
    vec2 edgeOffset=vec2(edgeGrain-.5,brushGrain(brushUv+31.7)-.5)*20.;
    vec2 exposure=texture2D(dye,screen+(driftPx+edgeOffset)/viewport).rg;
    float threshold=.105+edgeGrain*.09;
    float stroke=smoothstep(threshold*.78,threshold*1.15,exposure.r);
    float resting=smoothstep(threshold*.55,threshold*1.35,exposure.g)*.22;
    // Past segments fade independently, without a circle clipping the path.
    unveiling=max(stroke*.94,resting);
  }
  float wave=0.;
  if(ambientWave>.00001) {
    vec2 waveDistance=(screen-ambientOrigin)*vec2(viewport.x/viewport.y,1.);
    wave=exp(-pow(waveDistance.y+sin(waveDistance.x*5.+time*.45)*.04,2.)/.004-dot(waveDistance,waveDistance)*2.)*ambientWave;
  }
  float light=clamp(ink*.65+unveiling+wave*.45+pearlescence*.32,0.,1.);
  float visible=light;
  if(isCard>.5) {
    float spread=step(.995,reveal);
    if(reveal>.001 && reveal<.995) {
      spread=1.-smoothstep(reveal*1.7-.15,reveal*1.7+.05,length(vUv-origin)+noise(vUv*2.+flow*.01)*.14);
    }
    visible=max(light*.72,spread);
  }
  float imageAspect=imageSize.x/imageSize.y;
  float panelAspect=panelSize.x/panelSize.y;
  vec2 crop=vec2(min(panelAspect/imageAspect,1.),min(imageAspect/panelAspect,1.));
  vec2 uv=(vUv-.5)*crop+.5;
  vec2 blur=(1.-visible)*1.2/imageSize;
  vec3 col=(texture2D(map,uv).rgb*4.+texture2D(map,uv+blur).rgb+texture2D(map,uv-blur).rgb)/6.;
  if(isCard<.5 && detailReady>.5 && unveiling>.001) {
    float detailAspect=detailSize.x/detailSize.y;
    vec2 detailCrop=vec2(min(panelAspect/detailAspect,1.),min(detailAspect/panelAspect,1.));
    // The revealed scene shares the original camera and architecture, including
    // its floor. Uncover it across the whole scene so floor discoveries remain
    // visible; the moving brush and its decay are unchanged.
    vec3 revealedScene=texture2D(detailMap,(vUv-.5)*detailCrop+.5).rgb;
    col=mix(col,revealedScene,unveiling*.92);
  }
  float brightness=mix(.10+visible*.85,.22+visible*.78,isCard);
  col*=brightness;
  vec3 silver=vec3(.52,.68,.77), gold=vec3(.83,.73,.55);
  vec3 tint=mix(silver,gold,fold);
  float ribbons=ink*fold*.3;
  vec3 sceneGlow=tint*(ink*grain*.06+ribbons*.08+wave*.025+pearlescence*.12);
  col+=sceneGlow*(1.-isCard*.72);
  gl_FragColor=vec4(col,mix(1.,surfaceOpacity,isCard));
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;
type Cover = {
  image: HTMLImageElement; card: HTMLElement; mesh: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>;
  bounds: DOMRect; reveal: number; origin: THREE.Vector2; source: string;
};

/** One renderer and one fluid field serve the backdrop and every visible cover. */
export function createAtmosphere(canvas: HTMLCanvasElement, root: HTMLElement, paused: () => boolean) {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: "low-power" });
  if (!renderer.extensions.has("EXT_color_buffer_float")) { renderer.dispose(); throw new Error("Float targets unavailable"); }
  let fluid: FluidSimulation;
  try { fluid = new FluidSimulation(renderer, { profile: "performance", dyeResolution: 512, densityDissipation: .95, velocityDissipation: .96, dyeDissipation: .935, enableVorticity: true, curlStrength: 12, bfecc: false, reflectWalls: false }); }
  catch (error) { renderer.dispose(); throw error; }
  fluid.enableDye = true;
  const scene = new THREE.Scene();
  let canvasBounds = canvas.getBoundingClientRect();
  const camera = new THREE.OrthographicCamera(0, canvasBounds.width, canvasBounds.height, 0, -10, 10);
  const geometry = new THREE.PlaneGeometry(1, 1);
  const covers = new Map<HTMLImageElement, Cover>();
  const textures = new Map<string, THREE.Texture>();
  const bitmaps = new Set<ImageBitmap>();
  let revealTexture: THREE.Texture | null = null;
  let disposed = false, frame = 0, dirty = true, width = 0, height = 0;
  const frameBudget = new FrameBudget();
  let lastTime = performance.now(), nextAmbient = lastTime + 1500, ambientUntil = 0;
  let ambientX = .5, ambientY = .5, ambientBegan = 0, ambientDuration = 1, broadAmbient = false;
  const pendingPoints: RevealPoint[] = [];
  const content = root.querySelector<HTMLElement>(".lobby-main");
  const pointer = new THREE.Vector2(-2, -2);
  const pointerClient = new THREE.Vector2(-2, -2);
  let pointerActive = 0;
  let lastIdleSplat = 0, clearPointerDye = false;
  let painted: RevealPoint | null = null;
  let pointerCard: HTMLElement | null = null;
  const material = (isCard: boolean) => new THREE.ShaderMaterial({
    vertexShader, fragmentShader, depthTest: false, depthWrite: false, transparent: isCard,
    uniforms: {
      map: { value: null }, density: { value: fluid.densityTexture }, velocity: { value: fluid.velocityTexture }, dye: { value: fluid.dyeTexture },
      detailMap: { value:null }, detailSize: { value:new THREE.Vector2(1,1) }, detailReady: { value:0 },
      viewport: { value: new THREE.Vector2(width, height) }, imageSize: { value: new THREE.Vector2(1, 1) },
      panelSize: { value: new THREE.Vector2(width, height) }, rect: { value: new THREE.Vector4(0, 0, width, height) },
      origin: { value: new THREE.Vector2(.5, .5) },
      surfaceOpacity: { value: 1 }, ambientWave: { value: 0 }, ambientOrigin: { value: new THREE.Vector2(.5, .5) },
      time: { value: 0 }, reveal: { value: 0 }, isCard: { value: isCard ? 1 : 0 },
    },
  });
  const background = new THREE.Mesh(geometry, material(false));
  background.renderOrder = 0;
  scene.add(background);
  function loadImage(source: string, done: (texture: THREE.Texture) => void, decoded?: HTMLImageElement) {
    const cached = textures.get(source);
    if (cached) { if (cached.userData.ready) done(cached); else cached.userData.listeners.push(done); return; }
    const element = decoded || new Image();
    if (!decoded) { element.crossOrigin = 'anonymous'; element.fetchPriority = 'low'; element.src = source; }
    const texture = new THREE.Texture();
    texture.userData.listeners = [done];
    textures.set(source, texture);
    void element.decode().then(async () => {
      if (disposed) { texture.dispose(); return; }
      // DOM width/height are layout dimensions. WebGL allocates using those
      // properties, so upload an intrinsic-sized copy of the decoded pixels.
      // This reuses the selected srcset resource without another network load.
      if (typeof createImageBitmap === 'function') {
        const bitmap = await createImageBitmap(element, { imageOrientation: 'flipY', premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
        if (disposed) { bitmap.close(); texture.dispose(); return; }
        bitmaps.add(bitmap);
        texture.image = bitmap;
        texture.flipY = false;
      } else {
        const pixels = document.createElement('canvas');
        pixels.width = element.naturalWidth; pixels.height = element.naturalHeight;
        pixels.getContext('2d')!.drawImage(element, 0, 0);
        texture.image = pixels;
      }
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.needsUpdate = true;
      texture.userData.ready = true;
      texture.userData.listeners.forEach((callback: (texture: THREE.Texture) => void) => callback(texture));
      texture.userData.listeners = [];
    }).catch(() => { /* The readable DOM image remains the fallback. */ });
  }
  loadImage("/lobby/theatre.webp", texture => {
    background.material.uniforms.map.value = texture;
    background.material.uniforms.imageSize.value.set((texture.image as HTMLImageElement).width, (texture.image as HTMLImageElement).height);
  }, document.querySelector<HTMLImageElement>('.backdrop-home') || undefined);
  loadImage("/lobby/palace-revealed.webp", texture => { revealTexture=texture; });
  function syncCovers() {
    const images = new Set(root.querySelectorAll<HTMLImageElement>(".card-cover-media"));
    covers.forEach((cover, image) => {
      if (!images.has(image) || image.currentSrc !== cover.source) {
        scene.remove(cover.mesh); cover.mesh.material.dispose(); delete image.dataset.gpu; covers.delete(image);
      }
    });
    images.forEach(image => {
      if (covers.has(image) || !image.complete || !image.naturalWidth) return;
      const card = image.closest<HTMLElement>(".lobby-card")!;
      const mesh = new THREE.Mesh(geometry, material(true));
      mesh.renderOrder = 1; mesh.visible = false;
      const cover = { image, card, mesh, bounds: image.getBoundingClientRect(), reveal: 0, origin: new THREE.Vector2(.5, .5), source: image.currentSrc };
      covers.set(image, cover); scene.add(mesh);
      loadImage(cover.source, texture => {
        if (!image.isConnected || covers.get(image) !== cover) return;
        mesh.material.uniforms.map.value = texture;
        mesh.material.uniforms.imageSize.value.set((texture.image as HTMLImageElement).width, (texture.image as HTMLImageElement).height);
        dirty = true;
      }, image);
    });
  }
  const resize = () => {
    // CSS 100% excludes a classic scrollbar; innerWidth does not. The camera,
    // mesh positions and pointer must all use the canvas's actual CSS rectangle.
    canvasBounds = canvas.getBoundingClientRect();
    const nextWidth = Math.max(1, canvasBounds.width), nextHeight = Math.max(1, canvasBounds.height);
    if (nextWidth === width && nextHeight === height) return false;
    width = nextWidth; height = nextHeight;
    painted = null; pendingPoints.length = 0;
    renderer.setPixelRatio(Math.min(devicePixelRatio, width < 900 ? 1 : 1.25));
    renderer.setSize(width, height, false); fluid.resize(width, height);
    // Reallocating render targets is a new warm-up, not sustained device slowness.
    frameBudget.reset();
    camera.right = width; camera.top = height; camera.updateProjectionMatrix();
    background.position.set(width / 2, height / 2, 0); background.scale.set(width, height, 1);
    background.material.uniforms.rect.value.set(0, 0, width, height);
    background.material.uniforms.panelSize.value.set(width, height); dirty = true;
    return true;
  };
  const markDirty = () => { dirty = true; };
  const move = (event: PointerEvent) => {
    if (event.pointerType === "touch" || paused()) return;
    const x = (event.clientX - canvasBounds.left) / width, y = 1 - (event.clientY - canvasBounds.top) / height;
    pointerClient.set(event.clientX, event.clientY);
    // Record real input samples rather than easing the source toward the cursor.
    const events = event.getCoalescedEvents?.() ?? [];
    for (const sample of [...events, event]) {
      const point = { x: sample.clientX-canvasBounds.left, y: height-(sample.clientY-canvasBounds.top) };
      const last = pendingPoints[pendingPoints.length-1] ?? painted;
      if (!last || Math.hypot(point.x-last.x, point.y-last.y)>.25) pendingPoints.push(point);
    }
    if (pendingPoints.length>32) pendingPoints.splice(0,pendingPoints.length-32);
    pointer.set(x, y); pointerActive = 1;
    canvas.dataset.pointer = event.clientX + "," + event.clientY;
    const enteredCard = (event.target as Element).closest<HTMLElement>(".lobby-card");
    covers.forEach(cover => {
      if (cover.card === enteredCard && pointerCard !== enteredCard) {
        const bounds = cover.image.getBoundingClientRect();
        cover.origin.set(Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)), Math.max(0, Math.min(1, 1 - (event.clientY - bounds.top) / bounds.height)));
      }
    });
    pointerCard = enteredCard;
  };
  const leave = () => { pointerActive = 0; pointerCard = null; pendingPoints.length = 0; painted = null; };
  const observer = new MutationObserver(markDirty);
  observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ["src", "srcset", "sizes"] });
  const resizeObserver = new ResizeObserver(markDirty);
  resizeObserver.observe(root);
  resizeObserver.observe(canvas);
  const contextLost = (event: Event) => { event.preventDefault(); cleanup(); root.dataset.renderer = "fallback"; };
  canvas.addEventListener("webglcontextlost", contextLost);
  window.addEventListener("pointermove", move, { passive: true });
  document.documentElement.addEventListener("pointerleave", leave);
  window.addEventListener("blur", leave);
  window.addEventListener("scroll", markDirty, { passive: true });
  window.addEventListener("resize", resize);
  root.addEventListener("load", markDirty, true);
  const visibility = () => { leave(); clearPointerDye=true; lastTime = performance.now(); frameBudget.reset(); if (!document.hidden && !frame) frame = requestAnimationFrame(draw); };
  document.addEventListener("visibilitychange", visibility);
  resize();
  function draw(now: number) {
    frame = 0;
    if (disposed || document.hidden) return;
    frame = requestAnimationFrame(draw);
    const delta = Math.min(Math.max((now - lastTime) / 1000, .001), .035); lastTime = now;
    const viewportChanged = resize();
    const isPaused = paused();
    if (isPaused) {
      leave(); clearPointerDye=true;
      frameBudget.reset();
      if (!dirty && !viewportChanged) return;
    }
    if (!isPaused && frameBudget.exceeded(now)) {
      cleanup();
      root.dataset.renderer = "fallback";
      return;
    }
    const transitioning = root.classList.contains("is-transitioning");
    const surfaceOpacity = content ? Number(getComputedStyle(content).opacity) : 1;
    if (pointerActive) pointer.set((pointerClient.x - canvasBounds.left) / width, 1 - (pointerClient.y - canvasBounds.top) / height);
    if (dirty || transitioning) { syncCovers(); dirty = false; }
    // Transforms (including the tap spring) do not trigger ResizeObserver.
    covers.forEach(cover => { cover.bounds = cover.image.getBoundingClientRect(); });
    if (!isPaused && now > nextAmbient) {
      ambientX = .12 + Math.random() * .76; ambientY = .12 + Math.random() * .72;
      ambientBegan = now; ambientDuration = 2800 + Math.random() * 1000;
      ambientUntil = now + ambientDuration; nextAmbient = now + 4200 + Math.random() * 2000;
      broadAmbient = Math.random() < .35;
    }
    if (!isPaused && now < ambientUntil) {
      const phase = (now - ambientBegan) / ambientDuration;
      const x = ambientX + Math.sin(now * .0009) * .045, y = ambientY + Math.cos(now * .0011) * .025;
      const breath = Math.sin(Math.min(1, phase) * Math.PI) * delta * 60;
      // Keep the soft blue illumination and add a co-located curling paint glint.
      fluid.addSplat(x, y, Math.cos(now * .001) * .65, Math.sin(now * .001) * .65, {
        radius: broadAmbient ? .005 : .003, color: [0, .035 * breath, .045 * breath],
      });
    }
    if (!isPaused && pointerActive) {
      const point = { x:pointer.x*width, y:pointer.y*height };
      const path = pendingPoints.splice(0);
      if (painted) path.unshift(painted);
      const samples = sampleRevealPath(path);
      const distance = samples.reduce((sum,sample)=>sum+sample.distance,0);
      const speed = Math.min(1, distance / Math.max(delta, .001) / 1400);
      const radiusPx = 38+speed*8;
      for (const sample of samples) {
        // Spatial deposition keeps a quick pass legible without piling up a
        // bright pool when many events arrive at nearly the same coordinate.
        const dose = Math.min(.35,.18*(sample.distance/18+delta*15));
        // The brush opens immediately at the event, with its wider body behind
        // the leading edge. This offsets its footprint, not the pointer timing.
        fluid.addSplat((sample.x-sample.dx*radiusPx*.65)/width,(sample.y-sample.dy*radiusPx*.65)/height,sample.dx*.45,sample.dy*.45,{
          radius:Math.pow(radiusPx*2/height,2), color:[sample.dx*.45,sample.dy*.45,0], dyeColor:[dose,0,0],
        });
      }
      if (samples.length || now-lastIdleSplat>32) {
        // A separate channel holds only a small, dim glimpse at rest. It does
        // not keep the wider moving stroke alive after motion has stopped.
        fluid.addSplat(point.x/width,point.y/height,0,0,{
          radius:Math.pow(22*2/height,2), color:[0,0,0], dyeColor:[0,.045,0],
        });
        lastIdleSplat=now;
      }
      painted=point;
    }
    if (!isPaused) {
      // The library caps the simulation step at 1/60 s; compensate only the
      // pointer dye decay so its lifetime stays stable at 30/60/120 Hz.
      fluid.dyeDissipation=clearPointerDye ? 0 : Math.pow(.935,delta/Math.min(delta,1/60));
      fluid.step(delta); clearPointerDye=false;
    }
    const update = (mat: THREE.ShaderMaterial) => {
      mat.uniforms.density.value = fluid.densityTexture; mat.uniforms.dye.value = fluid.dyeTexture; mat.uniforms.velocity.value = fluid.velocityTexture;
      mat.uniforms.detailMap.value=revealTexture ?? mat.uniforms.map.value;
      mat.uniforms.detailReady.value=revealTexture ? 1 : 0;
      if(revealTexture) {
        const image=revealTexture.image as HTMLImageElement;
        mat.uniforms.detailSize.value.set(image.width,image.height);
      }
      mat.uniforms.viewport.value.set(width, height); mat.uniforms.time.value = now / 1000;
      mat.uniforms.surfaceOpacity.value = surfaceOpacity;
      mat.uniforms.ambientOrigin.value.set(ambientX, ambientY);
      mat.uniforms.ambientWave.value = broadAmbient && now < ambientUntil ? Math.sin((now - ambientBegan) / ambientDuration * Math.PI) : 0;
    };
    update(background.material);
    covers.forEach(cover => {
      const rect = cover.bounds;
      const left = rect.left - canvasBounds.left, top = rect.top - canvasBounds.top;
      const visible = top + rect.height > 0 && top < height && left + rect.width > 0 && left < width;
      cover.mesh.visible = visible && Boolean(cover.mesh.material.uniforms.map.value);
      if (!visible) return;
      const active = cover.card.matches(":hover, :focus-within");
      cover.reveal = active ? Math.min(1, cover.reveal + delta / .25) : Math.max(0, cover.reveal - delta / .8);
      const mat = cover.mesh.material;
      update(mat);
      mat.uniforms.reveal.value = cover.reveal; mat.uniforms.origin.value.copy(cover.origin);
      mat.uniforms.rect.value.set(left, height - top - rect.height, rect.width, rect.height);
      mat.uniforms.panelSize.value.set(rect.width, rect.height);
      cover.mesh.position.set(left + rect.width / 2, height - top - rect.height / 2, 1);
      cover.mesh.scale.set(rect.width, rect.height, 1);
    });
    renderer.setRenderTarget(null); renderer.render(scene, camera);
    // Keep the DOM backdrop and covers visible until a textured frame exists.
    // Texture download completion alone does not mean pixels have been drawn.
    if (background.material.uniforms.map.value) {
      if (root.dataset.renderer !== 'webgl') performance.mark('lobby:atmosphere-frame');
      root.dataset.renderer = "webgl";
      covers.forEach(cover => {
        if (cover.mesh.visible) cover.image.dataset.gpu = "ready";
      });
    }
  }
  frame = requestAnimationFrame(draw);
  function cleanup() {
    if (disposed) return;
    disposed = true; cancelAnimationFrame(frame); observer.disconnect(); resizeObserver.disconnect();
    window.removeEventListener("pointermove", move); document.documentElement.removeEventListener("pointerleave", leave); window.removeEventListener("blur", leave);
    window.removeEventListener("scroll", markDirty); window.removeEventListener("resize", resize);
    root.removeEventListener("load", markDirty, true); document.removeEventListener("visibilitychange", visibility);
    canvas.removeEventListener("webglcontextlost", contextLost);
    covers.forEach(cover => { delete cover.image.dataset.gpu; cover.mesh.material.dispose(); });
    textures.forEach(texture => texture.dispose());
    bitmaps.forEach(bitmap => bitmap.close());
    background.material.dispose(); geometry.dispose(); fluid.dispose(); renderer.dispose();
  }
  return cleanup;
}
