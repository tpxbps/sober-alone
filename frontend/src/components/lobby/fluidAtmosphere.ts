import * as THREE from "three";
import { FluidSimulation } from "three-fluid-fx";
import { FrameBudget } from "./frameBudget";

const vertexShader = `
varying vec2 vUv;
void main() { vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }
`;
const fragmentShader = `
uniform sampler2D map, density, velocity, dye;
uniform vec2 viewport, imageSize, panelSize, origin, pointer;
uniform vec4 rect;
uniform float time, reveal, isCard, pointerActive, surfaceOpacity, ambientWave;
uniform vec2 ambientOrigin;
varying vec2 vUv;
float noise(vec2 p) {
  return .5+.25*sin(p.x*7.1+sin(p.y*8.2+time*.55))+.25*cos(p.y*10.3+sin(p.x*5.4-time*.37));
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

  // The pointer changes how much of the existing image is visible. It has no
  // emissive core, rings or drawn contour: only advected exposure remains.
  vec2 pixels=screen*viewport;
  vec2 driftPx=clamp(flow*.35,vec2(-8.),vec2(8.));
  float driftNoise=noise(pixels/170.+flow*.0015);
  vec2 exposureUv=screen+(driftPx+vec2(driftNoise-.5,noise(pixels.yx/190.)-.5)*13.)/viewport;
  float exposure=texture2D(dye,exposureUv).r;
  float distanceToPointer=length((screen-pointer)*viewport);
  float proximity=1.-smoothstep(90.,220.,distanceToPointer);
  float unveiling=(1.-exp(-max(0.,exposure-.008)*2.8));
  unveiling*=mix(.72,1.,driftNoise)*proximity;
  unveiling=min(unveiling,.72);
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
  try { fluid = new FluidSimulation(renderer, { profile: "performance", dyeResolution: 512, densityDissipation: .95, velocityDissipation: .96, dyeDissipation: .94, enableVorticity: true, curlStrength: 12, bfecc: false, reflectWalls: false }); }
  catch (error) { renderer.dispose(); throw error; }
  fluid.enableDye = true;
  const scene = new THREE.Scene();
  let canvasBounds = canvas.getBoundingClientRect();
  const camera = new THREE.OrthographicCamera(0, canvasBounds.width, canvasBounds.height, 0, -10, 10);
  const geometry = new THREE.PlaneGeometry(1, 1);
  const loader = new THREE.TextureLoader();
  const covers = new Map<HTMLImageElement, Cover>();
  const textures = new Map<string, THREE.Texture>();
  let disposed = false, frame = 0, dirty = true, width = 0, height = 0;
  const frameBudget = new FrameBudget();
  let lastTime = performance.now(), nextAmbient = lastTime + 1500, ambientUntil = 0;
  let ambientX = .5, ambientY = .5, ambientBegan = 0, ambientDuration = 1, broadAmbient = false;
  let pendingSplat: { x: number; y: number; dx: number; dy: number } | null = null;
  const content = root.querySelector<HTMLElement>(".lobby-main");
  const pointer = new THREE.Vector2(-2, -2);
  const pointerClient = new THREE.Vector2(-2, -2);
  let pointerActive = 0;
  let lastMoved = 0, lastIdleSplat = 0;
  let painted: THREE.Vector2 | null = null;
  let pointerCard: HTMLElement | null = null;
  const material = (isCard: boolean) => new THREE.ShaderMaterial({
    vertexShader, fragmentShader, depthTest: false, depthWrite: false, transparent: isCard,
    uniforms: {
      map: { value: null }, density: { value: fluid.densityTexture }, velocity: { value: fluid.velocityTexture }, dye: { value: fluid.dyeTexture },
      viewport: { value: new THREE.Vector2(width, height) }, imageSize: { value: new THREE.Vector2(1, 1) },
      panelSize: { value: new THREE.Vector2(width, height) }, rect: { value: new THREE.Vector4(0, 0, width, height) },
      origin: { value: new THREE.Vector2(.5, .5) }, pointer: { value: pointer }, pointerActive: { value: 0 },
      surfaceOpacity: { value: 1 }, ambientWave: { value: 0 }, ambientOrigin: { value: new THREE.Vector2(.5, .5) },
      time: { value: 0 }, reveal: { value: 0 }, isCard: { value: isCard ? 1 : 0 },
    },
  });
  const background = new THREE.Mesh(geometry, material(false));
  background.renderOrder = 0;
  scene.add(background);
  function loadImage(source: string, done: (texture: THREE.Texture) => void) {
    const cached = textures.get(source);
    if (cached) { if (cached.image) done(cached); else cached.userData.listeners.push(done); return; }
    const texture = loader.load(source, loaded => {
      if (disposed) { loaded.dispose(); return; }
      loaded.colorSpace = THREE.SRGBColorSpace;
      loaded.userData.listeners.forEach((callback: (texture: THREE.Texture) => void) => callback(loaded));
      loaded.userData.listeners = [];
    }, undefined, () => { /* A failed GPU upload leaves the readable DOM image in place. */ });
    texture.userData.listeners = [done];
    textures.set(source, texture);
  }
  loadImage("/lobby/theatre.webp", texture => {
    background.material.uniforms.map.value = texture;
    background.material.uniforms.imageSize.value.set((texture.image as HTMLImageElement).width, (texture.image as HTMLImageElement).height);
  });
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
      });
    });
  }
  const resize = () => {
    // CSS 100% excludes a classic scrollbar; innerWidth does not. The camera,
    // mesh positions and pointer must all use the canvas's actual CSS rectangle.
    canvasBounds = canvas.getBoundingClientRect();
    const nextWidth = Math.max(1, canvasBounds.width), nextHeight = Math.max(1, canvasBounds.height);
    if (nextWidth === width && nextHeight === height) return false;
    width = nextWidth; height = nextHeight;
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
    if (!pointerActive || event.clientX !== pointerClient.x || event.clientY !== pointerClient.y) lastMoved = performance.now();
    pointerClient.set(event.clientX, event.clientY);
    const dx = pointerActive ? (x - pointer.x) * 220 : 0;
    const dy = pointerActive ? (y - pointer.y) * 220 : 0;
    // This is the source coordinate itself: never interpolate or ease it.
    pointer.set(x, y); pointerActive = 1;
    pendingSplat = { x, y, dx: Math.max(-12, Math.min(12, dx)), dy: Math.max(-12, Math.min(12, dy)) };
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
  const leave = () => { pointerActive = 0; pointerCard = null; pendingSplat = null; painted = null; };
  const observer = new MutationObserver(markDirty);
  observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ["src"] });
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
  const visibility = () => { lastTime = performance.now(); frameBudget.reset(); if (!document.hidden && !frame) frame = requestAnimationFrame(draw); };
  document.addEventListener("visibilitychange", visibility);
  resize();
  function draw(now: number) {
    frame = 0;
    if (disposed || document.hidden) return;
    frame = requestAnimationFrame(draw);
    const delta = Math.min((now - lastTime) / 1000, .035); lastTime = now;
    const viewportChanged = resize();
    const isPaused = paused();
    if (isPaused) {
      leave();
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
    if (!isPaused && pointerActive && (pendingSplat || now-lastIdleSplat>32)) {
      const moving = Math.exp(-(now-lastMoved)/220);
      const from = painted ?? pointer;
      const travel = new THREE.Vector2((pointer.x-from.x)*width,(pointer.y-from.y)*height);
      // Never interpolate the source's position across frames. All samples,
      // including the latest coordinate, are painted in this same frame.
      const distance = travel.length();
      const count = pendingSplat ? Math.min(6,Math.max(1,Math.ceil(distance/18))) : 1;
      const start = distance>220 ? 1-220/distance : 0;
      const radiusPx = 26+moving*20;
      const radius = Math.pow(radiusPx*2/height,2);
      const dose = pendingSplat ? (.025+.095*moving)/count : .017;
      const direction = travel.clone().normalize().multiplyScalar(.7*moving);
      for(let i=1;i<=count;i++) {
        const t=start+(1-start)*i/count;
        const x=from.x+(pointer.x-from.x)*t, y=from.y+(pointer.y-from.y)*t;
        // In three-fluid-fx 0.1.0 color.xy is also written into velocity.
        // Reserve density.z for ambient illumination and dye.r for exposure.
        fluid.addSplat(x,y,direction.x,direction.y,{
          radius, color:[direction.x,direction.y,0], dyeColor:[dose,0,0],
        });
      }
      painted=pointer.clone(); pendingSplat=null; lastIdleSplat=now;
    }
    if (!isPaused) fluid.step(delta);
    const update = (mat: THREE.ShaderMaterial) => {
      mat.uniforms.density.value = fluid.densityTexture; mat.uniforms.dye.value = fluid.dyeTexture; mat.uniforms.velocity.value = fluid.velocityTexture;
      mat.uniforms.viewport.value.set(width, height); mat.uniforms.time.value = now / 1000;
      mat.uniforms.pointerActive.value = pointerActive;
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
    background.material.dispose(); geometry.dispose(); fluid.dispose(); renderer.dispose();
  }
  return cleanup;
}
