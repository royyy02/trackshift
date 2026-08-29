let ws;
let timeData = [];
let socData = [];
let eReqData = [];
let currentSeed = null;
let lapTimes = []; // [{lap, time_s}]
let raceConfig = { trackClass: 'Balanced', laps: 5 };
let raceIsActive = false;
let isFleetMode = false;

// Full-fidelity race record, kept for PDF export -- unlike timeData/socData/eReqData above
// (capped to the last 200 samples so the live Chart.js line stays cheap to redraw every tick),
// these are never trimmed, so the exported report always covers the entire race, not just
// whatever the live chart currently happens to be showing.
let historyLog = []; // [{time, soc_mj, e_req, velocity_kmh, deploy_kw, regen_kw, lap, action}]
let timelineEvents = []; // plain strings, mirrors what addTimelineEvent() renders into the DOM
let lastFinishData = null; // the most recent 'finished' websocket message, verbatim
let lastBaselineResults = null; // the most recent 'baseline_results' message's `baselines` array

function toggleFleetMode() {
    isFleetMode = document.getElementById('fleet-toggle').checked;

    // Update labels to sell the domain transfer
    const modeLabel = isFleetMode ? 'EV DELIVERY FLEET' : 'F1 MOTORSPORT';
    document.getElementById('mode-label').innerText = modeLabel;

    // Mirror the toggle in the header so the active domain is visible even when the dock is
    // collapsed, not just as a checkbox state buried in the Setup tab.
    document.getElementById('mode-indicator-text').textContent = modeLabel;
    document.getElementById('mode-indicator').classList.toggle('fleet', isFleetMode);

    // Send command to backend
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ command: "set_mode", mode: isFleetMode ? 'fleet' : 'f1' }));
    }

    // The backend stops the current run when the mode switches (the new vehicle/battery
    // config wouldn't match an in-progress race), but that happens silently over the
    // websocket with no dedicated message back -- surface it here instead of leaving the
    // dashboard showing a frozen "LIVE" race that's actually no longer being simulated.
    if (raceIsActive) {
        showToast(`SWITCHED TO ${isFleetMode ? 'EV FLEET' : 'F1 MOTORSPORT'} MODE — PRESS START TO RACE`, 'warn');
        raceIsActive = false;
        setStatusPill('connected', 'CONNECTED');
        document.getElementById('btn-start').disabled = false;
    }
}

// --- Responsive layout ---
// The header wraps onto a second line on narrow viewports (flex-wrap in style.css), so its
// height isn't a fixed constant -- every fixed-position panel below it (.dock, .right-dock)
// reads this custom property for its own top offset instead of a hardcoded pixel value, so they
// always sit right below the header regardless of how tall it currently is.
const mainHeaderEl = document.querySelector('.main-header');
if (mainHeaderEl && 'ResizeObserver' in window) {
    // Deliberately re-measure via offsetHeight inside the callback rather than using the
    // ResizeObserver entry's own contentRect -- contentRect reports the content box only
    // (excludes padding/border), but .main-header has real vertical padding, so contentRect
    // under-reports the header's actual rendered (border-box) height by exactly that padding.
    // Every panel below it then anchors itself ~24px too high and visibly tucks up under the
    // header's second row whenever it wraps on a narrower viewport.
    const headerResizeObserver = new ResizeObserver(() => {
        document.documentElement.style.setProperty('--header-h', `${mainHeaderEl.offsetHeight}px`);
    });
    headerResizeObserver.observe(mainHeaderEl);
}

// --- Three.js Setup ---
const trackContainer = document.getElementById('track-container');
const cameraHint = document.getElementById('camera-hint');
const scene = new THREE.Scene();
// Matches the dashboard's own --bg-color (style.css) instead of the previous off-white, which
// read as a jarring blank void against the dark glass-panel UI around it. Fog fades the track
// into that same color at distance instead of a hard horizon cut, for a bit of depth.
scene.background = new THREE.Color(0x0b0f19);
scene.fog = new THREE.Fog(0x0b0f19, 300, 4000);

const camera = new THREE.PerspectiveCamera(60, trackContainer.clientWidth / trackContainer.clientHeight, 0.1, 20000);
camera.position.set(0, 45, 45);

// antialias is off and powerPreference is forced to 'high-performance' for real-world laptop
// performance, not raw visual quality: on hybrid-graphics laptops (integrated + discrete GPU),
// browsers default WebGL context creation to the low-power integrated GPU unless a page
// explicitly asks otherwise -- that alone can be the difference between smooth and "lags a lot,
// like a lot" on the exact same hardware. MSAA (antialias:true) is also one of the single most
// expensive WebGL context flags on weaker/integrated GPUs, and buys very little here since the
// track is a thin flattened ribbon viewed from a distance, not the kind of high-contrast hard
// edge antialiasing is worth its cost for.
const renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'high-performance' });
renderer.setSize(trackContainer.clientWidth, trackContainer.clientHeight);
trackContainer.appendChild(renderer.domElement);

// Lighting
const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
scene.add(ambientLight);
const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
dirLight.position.set(0, 100, 50);
scene.add(dirLight);

// Grid Helper for ground -- dim slate lines meant to read as a subtle surface texture on the
// dark scene, not the light-mode checkerboard (0x94a3b8/0xcbd5e1) this used to be. 300 divisions
// (not the 2000 this briefly was) -- purely decorative background geometry doesn't need to be
// nearly that dense, and at 2000 divisions a 20000-unit grid packs lines closer together than a
// pixel at any real camera distance, which both wastes GPU time rendering lines nobody can
// resolve and produces visible moire/flicker from the aliasing of it, which itself reads as
// "laggy" even when the frame rate is fine.
const gridHelper = new THREE.GridHelper(20000, 300, 0x2a3348, 0x141826);
gridHelper.position.y = -0.5;
scene.add(gridHelper);

// --- Camera controls: OrbitControls power both "Orbit Car" and "Free Roam" modes.
// "Chase Cam" mode disables OrbitControls entirely and drives the camera programmatically.
const controls = new THREE.OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 6;
controls.maxDistance = 400;
controls.maxPolarAngle = Math.PI * 0.495; // don't let the camera dip below the ground plane
controls.target.set(0, 0, 0);

const cameraHints = {
    chase: 'CHASE CAM — rigid follow, scroll to zoom',
    orbit: 'ORBIT (LOCK-ON) — drag to rotate, scroll to zoom, rigid follow',
    free: 'FREE ROAM — drag to rotate, right-drag to pan, scroll to zoom',
};

function setCameraMode(mode) {
    cameraMode = mode;
    controls.enabled = (mode !== 'chase');
    if (cameraHint) cameraHint.textContent = cameraHints[mode];
}

// Initialize from whatever the <select> actually shows rather than a value hardcoded here --
// previously this was hardcoded to 'orbit' while the HTML's default selected option was
// 'chase', so on load the dropdown *displayed* "CHASE CAM" while the real internal mode (and
// therefore which zoom/drag path was live) was actually orbit. Reading the select's own value
// guarantees the label and the behavior always agree, on load and after any future HTML edits.
let cameraMode = document.getElementById('camera-mode-select').value;
setCameraMode(cameraMode);

let chaseCamZoom = 1.0;
window.addEventListener('wheel', (e) => {
    if (cameraMode === 'chase') {
        chaseCamZoom += e.deltaY * 0.002;
        if (chaseCamZoom < 0.2) chaseCamZoom = 0.2;
        if (chaseCamZoom > 20.0) chaseCamZoom = 20.0;
    }
});

document.getElementById('camera-mode-select').addEventListener('change', (e) => {
    setCameraMode(e.target.value);
});

// Car Group (holds FBX model or placeholder, plus aura)
const carGroup = new THREE.Group();
scene.add(carGroup);

// Placeholder Car
const phGeo = new THREE.BoxGeometry(2, 1, 4);
const phMat = new THREE.MeshLambertMaterial({ color: 0x94a3b8 });
const placeholder = new THREE.Mesh(phGeo, phMat);
carGroup.add(placeholder);

// Strategy Aura
const auraGeo = new THREE.PlaneGeometry(8, 12);
const auraMat = new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.5, side: THREE.DoubleSide });
const aura = new THREE.Mesh(auraGeo, auraMat);
aura.rotation.x = -Math.PI / 2;
aura.position.y = 0.1; // slightly above road
carGroup.add(aura);

// FBX Loader
let loadedCar = null;

if (typeof THREE.FBXLoader !== 'undefined') {
    const loader = new THREE.FBXLoader();
    loader.load('/static/f1_car.fbx', function (object) {
        // Success
        carGroup.remove(placeholder);
        
        loadedCar = object;

        // Auto-scale and center the loaded FBX
        const box = new THREE.Box3().setFromObject(object);
        const size = box.getSize(new THREE.Vector3());

        // F1 cars are usually longest along the Z axis, but max dimension is safest
        const maxDim = Math.max(size.x, size.y, size.z);
        if (maxDim > 0) {
            // Increase scale to 12.0 (3x bigger) to compensate for models with large invisible bounds
            const scale = 12.0 / maxDim;
            object.scale.set(scale, scale, scale);
        }

        // We deliberately do NOT hardcode any rotations here.
        // Different 3D artists use completely different coordinate systems (Z-up vs Y-up).
        // The UI buttons (Pitch, Yaw, Roll) in the dashboard let the user fix any orientation.

        // Recalculate bounding box after scale and rotation
        const scaledBox = new THREE.Box3().setFromObject(object);
        const center = scaledBox.getCenter(new THREE.Vector3());

        // Center it horizontally, and set bottom to sit exactly on the track surface
        // The track has a slight thickness (Y=0.06), so we lift the car by 0.15 to prevent the nose/wing from clipping.
        object.position.x = -center.x;
        object.position.z = -center.z;
        object.position.y = -scaledBox.min.y + 0.15;
        
        // Enhance materials: FBXLoader often uses dull Phong materials. 
        // We upgrade them to a glossy Standard material to make it look like car paint.
        object.traverse(function(child) {
            if (child.isMesh) {
                const makeSleek = (mat) => {
                    if (!mat) return mat;
                    return new THREE.MeshStandardMaterial({
                        color: mat.color || 0x333333,
                        map: mat.map || null,
                        normalMap: mat.normalMap || null,
                        metalness: 0.6,
                        roughness: 0.3,
                        side: THREE.DoubleSide
                    });
                };
                
                if (Array.isArray(child.material)) {
                    child.material = child.material.map(makeSleek);
                } else {
                    child.material = makeSleek(child.material);
                }
            }
        });

        carGroup.add(object);
    }, undefined, function (error) {
        console.log("No f1_car.fbx found or failed to load. Using placeholder box.");
    });
}

let trackCurve = null;
let trackTotalLength = 0;
let trackMeshes = [];

// Corners are subdivided into many small steps so the resulting spline has a smooth,
// continuously-varying tangent instead of a coarse polyline -- that polygonal tangent noise
// was the main source of the camera/car jitter through corners, since both the car's heading
// and the chase camera's offset are derived from curve.getTangentAt(). MUST match the
// backend's CORNER_WALK_STEPS (core/track_generator.py) -- the backend solves the closing
// loop against exact circular-arc math using that same step count to predict where this
// polygon walk ends up, so a mismatched step count here reopens a small seam at the
// start/finish line even though the backend verifies the loop as closed.
const CORNER_STEPS = 64;

// Shared by the 3D track mesh and the 2D minimap so both always agree on the exact same
// geometry -- walks the same segment list once into a flat XZ point path.
function generateTrackPoints(segments) {
    let points = [{ x: 0, z: 0 }];
    let currentPos = { x: 0, z: 0 };
    let currentAngle = 0;
    let totalLength = 0;

    for (let seg of segments) {
        totalLength += seg.length;
        if (seg.radius === -1) {
            currentPos = {
                x: currentPos.x + Math.sin(currentAngle) * seg.length,
                z: currentPos.z + Math.cos(currentAngle) * seg.length,
            };
            points.push({ ...currentPos });
        } else {
            let theta = seg.length / seg.radius;
            // Each corner's turn direction is real generated data from the backend now (not
            // an alternating left/right guess) -- it's part of what the closing-loop math
            // (core/track_generator.py's _generate_closing_path) solves against, so this has
            // to draw the direction the backend actually chose, not invent its own.
            let dir = seg.direction;

            for (let i = 1; i <= CORNER_STEPS; i++) {
                let stepTheta = currentAngle + (dir * theta * (i / CORNER_STEPS));
                let stepDist = seg.length / CORNER_STEPS;
                currentPos = {
                    x: currentPos.x + Math.sin(stepTheta) * stepDist,
                    z: currentPos.z + Math.cos(stepTheta) * stepDist,
                };
                points.push({ ...currentPos });
            }
            currentAngle += dir * theta;
        }
    }

    return { points, totalLength };
}

function buildTrack(segments) {
    trackMeshes.forEach(m => scene.remove(m));
    trackMeshes = [];

    const { points: flatPoints, totalLength } = generateTrackPoints(segments);
    const points = flatPoints.map(p => new THREE.Vector3(p.x, 0, p.z));
    trackTotalLength = totalLength;

    buildMinimap(flatPoints);

    // 'centripetal' parameterization avoids the loops/overshoots that the default
    // parameterization can produce when point spacing is very uneven (straights vs. corners
    // here), which is another source of the previous spline's tangent noise.
    trackCurve = new THREE.CatmullRomCurve3(points, false, 'centripetal');
    // getPointAt()/getTangentAt() (used every animation frame below) convert the uniform
    // "distance around the lap" parameter into a curve parameter via an arc-length lookup
    // table that defaults to only 200 samples (THREE.Curve.arcLengthDivisions), no matter how
    // many points the curve has. Our point array is very unevenly dense -- each corner packs
    // in CORNER_STEPS (64) points over a short arc, while a straight is just 1-2 points over a
    // much longer one -- so with only 200 samples spread across a track that can have
    // thousands of points, almost none land inside any given corner. That starves the corner
    // of resolution in the lookup table, so position gets interpolated near-linearly across a
    // whole corner instead of following its curvature, producing an uneven, stuttering
    // (laggy-looking) car speed specifically through turns. Matching the table's resolution to
    // the actual point density fixes it. This is a one-time cost paid once per track build
    // (getLengths() caches the result), not per frame -- even 40000 divisions costs on the
    // order of 10-20ms to compute, so there's no reason to be stingy with it. Measured effect
    // on a real generated track's speed evenness (coefficient of variation of point-to-point
    // spacing sampled at fixed distance steps): CV 2.84 at the old default of 200 -> 0.61 at
    // divisions = point count -> 0.04 here -- roughly 70x smoother than the default.
    trackCurve.arcLengthDivisions = Math.max(40000, flatPoints.length * 10);

    // Flat asphalt-gray road. Was near-black (0x111111), tuned for contrast against the
    // scene's old off-white background -- on the current dark background that would nearly
    // disappear into it instead of reading as a track.
    // Segment counts trimmed from (points.length*2 capped at 4000, 8 radial) -- the curve's own
    // smoothness comes from CatmullRom interpolation + arcLengthDivisions above, not from how
    // many tube segments slice it, so that density bought triangle count, not visual quality.
    // Radial segments stay at 6 (not 8): the tube is flattened to 1% scale on Y right below, so
    // it reads as a flat ribbon either way -- the extra round-ness was invisible.
    const tubularSegments = Math.min(points.length, 2000);
    const tubeGeo = new THREE.TubeGeometry(trackCurve, tubularSegments, 6, 6, false);
    const tubeMat = new THREE.MeshLambertMaterial({ color: 0x3a3f4b, wireframe: false });

    const trackMesh = new THREE.Mesh(tubeGeo, tubeMat);
    // Flatten Y axis to make it a 2D road
    trackMesh.scale.y = 0.01;

    scene.add(trackMesh);
    trackMeshes.push(trackMesh);

    // Frame the car closely
    const box = new THREE.Box3().setFromObject(trackMesh);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const radius = Math.max(size.x, size.z) * 0.15 + 10;
    camera.position.set(center.x, radius * 0.4, center.z + radius);
    controls.target.set(center.x, 0, center.z);
    controls.update();
}

// --- 2D minimap: an SVG top-down projection of the exact same points buildTrack() drew in
// 3D, normalized into a fixed 200x200 viewBox with a live car marker updated each frame. ---
const MINIMAP_SIZE = 200;
const MINIMAP_PAD = 18;
let minimapProjector = null; // (x, z) -> {x, y} in SVG space, set fresh per track

function buildMinimap(flatPoints) {
    const svg = document.getElementById('minimap-svg');
    if (!svg) return;
    svg.innerHTML = '';

    const xs = flatPoints.map(p => p.x);
    const zs = flatPoints.map(p => p.z);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minZ = Math.min(...zs), maxZ = Math.max(...zs);
    const spanX = Math.max(1, maxX - minX);
    const spanZ = Math.max(1, maxZ - minZ);
    const scale = (MINIMAP_SIZE - MINIMAP_PAD * 2) / Math.max(spanX, spanZ);
    const offsetX = (MINIMAP_SIZE - spanX * scale) / 2;
    const offsetY = (MINIMAP_SIZE - spanZ * scale) / 2;

    minimapProjector = (x, z) => ({
        x: (x - minX) * scale + offsetX,
        y: (z - minZ) * scale + offsetY,
    });

    // The generated track closes to within a few meters (backend chord-discretization
    // residual, see core/track_generator.py's CORNER_WALK_STEPS comment) -- 'Z' snaps that
    // last sliver shut for a crisp outline instead of a near-invisible but real gap.
    const pathD = flatPoints.map((p, i) => {
        const proj = minimapProjector(p.x, p.z);
        return `${i === 0 ? 'M' : 'L'}${proj.x.toFixed(1)},${proj.y.toFixed(1)}`;
    }).join(' ') + ' Z';

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', pathD);
    path.setAttribute('class', 'minimap-track');
    svg.appendChild(path);

    const startProj = minimapProjector(flatPoints[0].x, flatPoints[0].z);
    const startDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    startDot.setAttribute('cx', startProj.x);
    startDot.setAttribute('cy', startProj.y);
    startDot.setAttribute('r', 3);
    startDot.setAttribute('class', 'minimap-start');
    svg.appendChild(startDot);

    const carDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    carDot.setAttribute('id', 'minimap-car-dot');
    carDot.setAttribute('r', 4.5);
    carDot.setAttribute('class', 'minimap-car');
    carDot.setAttribute('cx', startProj.x);
    carDot.setAttribute('cy', startProj.y);
    svg.appendChild(carDot);
}

function updateMinimapCar(carPos) {
    if (!minimapProjector) return;
    const dot = document.getElementById('minimap-car-dot');
    if (!dot) return;
    const proj = minimapProjector(carPos.x, carPos.z);
    dot.setAttribute('cx', proj.x);
    dot.setAttribute('cy', proj.y);
}

let currentDistance = 0;
let targetDistance = 0;
let lastDistance = 0;
let lastTelemetryTime = performance.now();
let tickIntervalMs = 100; // updated from server telemetry once a race is running

// Smoothed car heading, decoupled from raw per-frame tangent noise via damped slerp.
const smoothedQuaternion = new THREE.Quaternion();
let smoothedQuaternionInit = false;

function update3DView(distance, action) {
    if (!trackCurve || trackTotalLength === 0) return;

    // Save last state for perfect time-based interpolation
    lastDistance = currentDistance;
    targetDistance = distance;
    lastTelemetryTime = performance.now();

    // Update aura color
    if (action.includes("ATTACK")) aura.material.color.setHex(0xef4444);
    else if (action.includes("HARVEST") || action.includes("REGEN")) aura.material.color.setHex(0x10b981);
    else if (action.includes("CONSERVE") || action.includes("INFEASIBLE")) aura.material.color.setHex(0xf59e0b);
    else aura.material.color.setHex(0x38bdf8);
}

// --- Telemetry HUD interpolation ---
// The server only sends one telemetry message per tick_interval_s (~100ms at 1x speed, longer
// at slower multipliers). Previously the gauges/values were written straight from that message,
// so they visibly jumped once per tick and jumped hard on a disturbance toggle's instantaneous
// physics change. This mirrors the 3D car's distance interpolation above: numeric HUD fields
// are lerped between the last two ticks every animation frame (60fps), driven by the same
// lastTelemetryTime/tickIntervalMs clock already kept in sync by update3DView().
const NUMERIC_TELEMETRY_FIELDS = ['velocity_kmh', 'soc_mj', 'soc_capacity_mj', 'deploy_kw', 'regen_kw', 'e_req', 'sig_e', 'r_safety', 'deployable'];
let lastTelemetrySnapshot = null;
let targetTelemetrySnapshot = null;

function currentTelemetryProgress() {
    const p = (performance.now() - lastTelemetryTime) / tickIntervalMs;
    return Math.max(0, Math.min(1, p));
}

function lerpTelemetry(a, b, t) {
    if (!a) return b;
    const out = {};
    for (const key of NUMERIC_TELEMETRY_FIELDS) {
        const av = a[key] ?? b[key] ?? 0;
        const bv = b[key] ?? av;
        out[key] = av + (bv - av) * t;
    }
    return out;
}

// Exponential, frame-rate-independent smoothing: converges toward `target` at a rate set by
// `speed`, but the fraction actually applied each frame is scaled by elapsed time (`dt`), so
// it looks the same whether the frame took 8ms or 40ms -- a fixed per-frame lerp factor
// (the previous implementation used a flat 0.3) doesn't have that property and visibly
// stutters whenever the frame rate isn't perfectly steady.
function dampedFactor(speed, dt) {
    return 1 - Math.exp(-speed * dt);
}

const clock = new THREE.Clock();
let previousLapIndex = 0;

function animate() {
    requestAnimationFrame(animate);
    const dt = Math.min(clock.getDelta(), 0.1); // clamp to avoid huge jumps after a tab is backgrounded

    if (targetTelemetrySnapshot) {
        renderTelemetryFrame(lerpTelemetry(lastTelemetrySnapshot, targetTelemetrySnapshot, currentTelemetryProgress()));
    }

    if (trackCurve && trackTotalLength > 0) {
        // Telemetry arrives roughly every `tickIntervalMs`. Linearly interpolate progress
        // between the last two known distances so the car moves continuously instead of
        // snapping once per telemetry message.
        let progress = (performance.now() - lastTelemetryTime) / tickIntervalMs;
        if (progress > 1.0) progress = 1.0;
        if (progress < 0.0) progress = 0.0;

        currentDistance = lastDistance + (targetDistance - lastDistance) * progress;

        // The rendered track geometry is a single open lap (procedurally generated, not
        // geometrically closed into a loop -- see core/track_generator.py's docstring on
        // why), replayed from the start on every lap. That means the seam where distance
        // wraps back to 0 is a genuine, large discontinuity in the curve's tangent -- NOT
        // something that should be smoothed through. Smoothing across it (as the previous
        // version of this code did unconditionally) is exactly what produced the camera
        // whipping upside-down/sideways for a frame at every lap boundary: the slerp/lerp
        // was interpolating toward a target on the *other end of the track*. Detect the
        // crossing and hard-snap instead.
        const lapIndexNow = Math.floor(currentDistance / trackTotalLength);
        const crossedLapSeam = lapIndexNow !== previousLapIndex;
        previousLapIndex = lapIndexNow;

        let lapDistance = currentDistance % trackTotalLength;
        let t = lapDistance / trackTotalLength;
        if (t < 0) t = 0;
        if (t > 1) t = 1;

        const carPos = trackCurve.getPointAt(t);
        const tangent = trackCurve.getTangentAt(t).normalize();

        carGroup.position.copy(carPos);
        updateMinimapCar(carPos);

        // Compute the raw target orientation from the tangent, then slerp the car's actual
        // orientation toward it with time-based damping instead of snapping to it directly
        // -- except right at a lap-seam crossing, where a hard snap is correct (see above).
        const lookAtPos = carPos.clone().add(tangent);
        const dummy = new THREE.Object3D();
        dummy.position.copy(carPos);
        dummy.lookAt(lookAtPos);
        if (!smoothedQuaternionInit || crossedLapSeam) {
            smoothedQuaternion.copy(dummy.quaternion);
            smoothedQuaternionInit = true;
        } else {
            smoothedQuaternion.slerp(dummy.quaternion, dampedFactor(10, dt));
        }
        carGroup.quaternion.copy(smoothedQuaternion);

        if (cameraMode === 'chase') {
            // Chase camera locked rigidly to the interpolated car position
            const cameraOffset = new THREE.Vector3(0, 4 * chaseCamZoom, -10 * chaseCamZoom);
            cameraOffset.applyQuaternion(carGroup.quaternion);
            const targetCameraPos = carPos.clone().add(cameraOffset);

            camera.position.copy(targetCameraPos);
            camera.lookAt(carPos.clone().add(new THREE.Vector3(0, 2 * chaseCamZoom, 0)));
        } else if (cameraMode === 'orbit') {
            // Keep the orbit target locked onto the car rigidly
            controls.target.copy(carPos);
            controls.update();
        } else {
            // Free roam: target is fixed (set once in buildTrack), user has full control.
            controls.update();
        }
    } else if (cameraMode !== 'chase') {
        controls.update();
    }

    renderer.render(scene, camera);
}
animate();

window.addEventListener('resize', () => {
    camera.aspect = trackContainer.clientWidth / trackContainer.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(trackContainer.clientWidth, trackContainer.clientHeight);
});
// --- End Three.js Setup ---


const ctx = document.getElementById('energyChart').getContext('2d');
const energyChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: timeData,
        datasets: [
            {
                label: 'Actual SOC (MJ)',
                data: socData,
                borderColor: '#ff2800',
                backgroundColor: 'rgba(255, 40, 0, 0.1)',
                fill: true,
                tension: 0.1,
                pointRadius: 0
            },
            {
                label: 'Predicted Requirement (MJ)',
                data: eReqData,
                borderColor: '#f59e0b',
                borderDash: [5, 5],
                tension: 0.1,
                pointRadius: 0
            }
        ]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
            x: { title: { display: true, text: 'Time (s)' } },
            y: { title: { display: true, text: 'Energy (MJ)' }, min: 0, max: 4.5 }
        }
    }
});

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = function() {
        setStatusPill('connected', 'CONNECTED');
        // The Start button is disabled by default (in the HTML) so a click landing before
        // the handshake completes can't throw "Still in CONNECTING state" on ws.send().
        if (!raceIsActive) document.getElementById('btn-start').disabled = false;
        // Re-sync the server with whatever speed the dropdown is currently set to
        // (e.g. after a reconnect).
        setSpeed(document.getElementById('speed-select').value);
    };

    ws.onmessage = function(event) {
        const msg = JSON.parse(event.data);
        if (msg.type === 'telemetry') {
            // Snapshot where the readouts are *currently* sitting (mid-interpolation from the
            // previous tick) as the new lerp's start point, before update3DView() below
            // overwrites lastTelemetryTime for the new tick -- exactly the same trick already
            // used for the 3D car's position, just applied to the numeric HUD too. Without
            // this, gauges/values only had one instantaneous value per tick_interval_s
            // (~100ms at 1x speed) with nothing in between, which reads as chunky/laggy, and a
            // disturbance toggle's physics jump would render as a hard instant snap rather
            // than an eased transition.
            lastTelemetrySnapshot = targetTelemetrySnapshot
                ? lerpTelemetry(lastTelemetrySnapshot, targetTelemetrySnapshot, currentTelemetryProgress())
                : msg;
            targetTelemetrySnapshot = msg;
            if (msg.tick_interval_s) tickIntervalMs = msg.tick_interval_s * 1000;
            applyDiscreteTelemetry(msg);
            update3DView(msg.distance, msg.action);
        } else if (msg.type === 'track_geometry') {
            if (msg.max_speed_kmh) MAX_SPEED_KMH = msg.max_speed_kmh;
            if (msg.max_power_kw) MAX_POWER_KW = msg.max_power_kw;
            buildTrack(msg.track);
            raceIsActive = true;
            setStatusPill('live', 'LIVE');
            document.getElementById('btn-start').disabled = true;
            const label = `${msg.track_class} · ${msg.laps_total} lap${msg.laps_total > 1 ? 's' : ''} · seed ${msg.seed}`;
            document.getElementById('seed-readout').innerText = msg.seed;
            showToast(`RACE STARTED — ${label}`, 'info');
        } else if (msg.type === 'lap_complete') {
            handleLapComplete(msg);
        } else if (msg.type === 'finished') {
            handleRaceFinished(msg);
        } else if (msg.type === 'baseline_results') {
            renderBaselineTable(msg.baselines);
        } else if (msg.type === 'status') {
            console.log(msg.message);
        }
    };

    ws.onclose = function() {
        setStatusPill('error', 'DISCONNECTED');
        setTimeout(connect, 2000);
    };
}

// Gauge full-scale values. Defaults match the F1 config, but the server sends the live values
// (derived from whichever regulation config is actually active -- F1 or EV-fleet mode, see
// toggleFleetMode()) on every track_geometry message, so these self-correct after a mode
// switch instead of staying hardcoded to F1's 380 km/h / 350 kW range.
let MAX_SPEED_KMH = 380;
let MAX_POWER_KW = 350;

// Called once per animation frame (60fps) with an already-interpolated telemetry snapshot --
// everything here is a smoothly-varying number, so it just writes it straight to the DOM. No
// rounding/threshold logic that would itself need to look "instant" lives here; that belongs
// in applyDiscreteTelemetry below.
function renderTelemetryFrame(data) {
    document.getElementById('val-speed').innerText = data.velocity_kmh.toFixed(1);
    const speedPct = Math.max(0, Math.min(100, (data.velocity_kmh / MAX_SPEED_KMH) * 100));
    document.getElementById('gauge-speed').style.setProperty('--pct', speedPct.toFixed(2));

    document.getElementById('val-soc').innerText = data.soc_mj.toFixed(2);
    const socCapacity = data.soc_capacity_mj || 4.0;
    const socPct = Math.max(0, Math.min(100, (data.soc_mj / socCapacity) * 100));
    const socGauge = document.getElementById('gauge-soc');
    socGauge.style.setProperty('--pct', socPct.toFixed(2));
    socGauge.classList.toggle('gauge-low', socPct < 20);

    // Power flow: deploy pushes the bar right of center, regen pushes it left.
    const netKw = data.deploy_kw - data.regen_kw;
    document.getElementById('val-power').innerText = netKw.toFixed(0);
    const powerPct = Math.max(-100, Math.min(100, (netKw / MAX_POWER_KW) * 100));
    const fillEl = document.getElementById('power-flow-fill');
    if (powerPct >= 0) {
        fillEl.style.left = '50%';
        fillEl.style.width = `${powerPct / 2}%`;
        fillEl.classList.remove('regen');
    } else {
        fillEl.style.left = `${50 + powerPct / 2}%`;
        fillEl.style.width = `${-powerPct / 2}%`;
        fillEl.classList.add('regen');
    }

    document.getElementById('val-ereq').innerText = data.e_req.toFixed(2);
    document.getElementById('val-sige').innerText = data.sig_e.toFixed(2);
    document.getElementById('val-rsafety').innerText = data.r_safety.toFixed(2);
    document.getElementById('val-deployable').innerText = data.deployable.toFixed(2);
}

let lastAction = "";
let lastFlags = { raining: false, safety_car: false, limited_power: false };

function addTimelineEvent(text) {
    const container = document.getElementById('timeline-container');
    if (!container) return;
    
    // Remove "No events yet" if present
    const emptyEl = container.querySelector('.timeline-empty');
    if (emptyEl) emptyEl.remove();
    
    const eventEl = document.createElement('div');
    eventEl.className = 'timeline-event';
    eventEl.innerText = text;

    container.appendChild(eventEl);
    container.scrollTop = container.scrollHeight;

    timelineEvents.push(text);
}

// Called once per telemetry message -- everything here is inherently a discrete/categorical
// state change (lap counter, flag lights, strategy label, chart samples), so there is nothing
// to interpolate; these should still update the instant the server reports them.
function applyDiscreteTelemetry(data) {
    document.getElementById('val-lap').innerText = `${data.lap} / ${data.total_laps}`;

    document.getElementById('btn-rain').classList.toggle('active-rain', data.raining);
    document.getElementById('btn-sc').classList.toggle('active-sc', data.safety_car);
    document.getElementById('btn-power').classList.toggle('active-power', data.limited_power);
    if (data.raining !== lastFlags.raining) {
        showToast(data.raining ? 'RAIN STARTED' : 'RAIN CLEARED', 'warn');
        addTimelineEvent(`[LAP ${data.lap}] ${data.raining ? 'RAIN DETECTED' : 'RAIN CLEARED'}`);
    }
    if (data.safety_car !== lastFlags.safety_car) {
        showToast(data.safety_car ? 'SAFETY CAR DEPLOYED' : 'SAFETY CAR IN', 'warn');
        addTimelineEvent(`[LAP ${data.lap}] ${data.safety_car ? 'SAFETY CAR DEPLOYED' : 'SAFETY CAR ENDED'}`);
    }
    if (data.limited_power !== lastFlags.limited_power) {
        showToast(data.limited_power ? 'MGU-K FAILURE' : 'MGU-K RESTORED', 'warn');
        addTimelineEvent(`[LAP ${data.lap}] ${data.limited_power ? 'MGU-K FAILURE' : 'MGU-K RESTORED'}`);
    }
    lastFlags = { raining: data.raining, safety_car: data.safety_car, limited_power: data.limited_power };

    const actionEl = document.getElementById('val-action');
    actionEl.innerText = data.action;
    actionEl.className = 'action-box';
    if (data.action.includes("ATTACK")) actionEl.classList.add("action-attack");
    else if (data.action.includes("HARVEST") || data.action.includes("REGEN")) actionEl.classList.add("action-harvest");
    else if (data.action.includes("COAST")) actionEl.classList.add("action-coast");
    else if (data.action.includes("CONSERVE") || data.action.includes("INFEASIBLE")) actionEl.classList.add("action-conserve");

    if (data.action !== lastAction) {
        if (lastAction) showToast(`STRATEGY: ${data.action}`, 'info');
        lastAction = data.action;
    }

    const overtakePanel = document.getElementById('overtake-panel');
    if (data.overtake_assessment) {
        overtakePanel.style.display = 'block';
        document.getElementById('overtake-reward').innerText = data.overtake_assessment.reward_s.toFixed(2);
        document.getElementById('overtake-cost').innerText = data.overtake_assessment.cost_mj.toFixed(2);
        
        const riskEl = document.getElementById('overtake-risk');
        riskEl.innerText = `RISK: ${data.overtake_assessment.risk} (${data.overtake_assessment.recommendation})`;
        
        overtakePanel.className = 'overtake-panel';
        if (data.overtake_assessment.risk === 'HIGH') {
            overtakePanel.classList.add('risk-high');
        } else if (data.overtake_assessment.risk === 'LOW') {
            overtakePanel.classList.add('risk-low');
        }
    } else {
        overtakePanel.style.display = 'none';
    }

    const robEl = document.getElementById('val-robustness');
    if (data.deployable > 0) {
        robEl.innerText = "ROBUSTNESS: HIGH (SAFE)";
        robEl.style.backgroundColor = "rgba(16, 185, 129, 0.15)";
        robEl.style.color = "var(--accent-green)";
        robEl.style.borderColor = "rgba(16, 185, 129, 0.3)";
    } else {
        robEl.innerText = "ROBUSTNESS: LOW (CONSERVE)";
        robEl.style.backgroundColor = "rgba(239, 68, 68, 0.15)";
        robEl.style.color = "var(--accent-red)";
        robEl.style.borderColor = "rgba(239, 68, 68, 0.3)";
    }

    timeData.push(data.time.toFixed(1));
    socData.push(data.soc_mj);
    eReqData.push(data.e_req);

    if (timeData.length > 200) {
        timeData.shift();
        socData.shift();
        eReqData.shift();
    }

    energyChart.update();

    // Uncapped -- see the historyLog declaration up top for why this doesn't share the
    // 200-sample trim above.
    historyLog.push({
        time: data.time,
        soc_mj: data.soc_mj,
        e_req: data.e_req,
        velocity_kmh: data.velocity_kmh,
        deploy_kw: data.deploy_kw,
        regen_kw: data.regen_kw,
        lap: data.lap,
        action: data.action,
    });
}

// --- Toasts ---
function showToast(text, kind) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${kind || 'info'}`;
    toast.textContent = text;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3100);
}

// --- Status pill ---
function setStatusPill(state, text) {
    const pill = document.getElementById('status-pill');
    const label = document.getElementById('status-pill-text');
    if (!pill || !label) return;
    pill.className = `status-pill ${state}`;
    label.innerText = text;
}

// --- Lap timing ---
function formatLapTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(2).padStart(5, '0');
    return `${m}:${s}`;
}

function handleLapComplete(msg) {
    lapTimes.push({ lap: msg.lap, time_s: msg.lap_time_s });
    renderLapTimes();
    showToast(`LAP ${msg.lap} — ${formatLapTime(msg.lap_time_s)}`, 'good');
}

function renderLapTimes() {
    const list = document.getElementById('lap-times-list');
    if (!list) return;
    if (lapTimes.length === 0) {
        list.innerHTML = '<div class="lap-times-empty">No laps completed yet</div>';
        return;
    }
    const best = Math.min(...lapTimes.map(l => l.time_s));
    list.innerHTML = lapTimes.map(l => `
        <div class="lap-time-row ${l.time_s === best ? 'best-lap' : ''}">
            <span class="lap-num">LAP ${l.lap}</span>
            <span class="lap-time">${formatLapTime(l.time_s)}</span>
        </div>
    `).reverse().join('');
}

// --- Race finished summary ---
function handleRaceFinished(msg) {
    lastFinishData = msg; // kept verbatim for the PDF export's summary section
    raceIsActive = false;
    setStatusPill('finished', 'FINISHED');
    document.getElementById('btn-start').disabled = false;
    showToast('RACE FINISHED', 'good');

    document.getElementById('finish-track-label').innerText =
        `${msg.track_class} · ${msg.total_laps} lap${msg.total_laps > 1 ? 's' : ''}`;
    document.getElementById('finish-time').innerText = formatLapTime(msg.total_time_s);
    document.getElementById('finish-avg-speed').innerHTML = `${msg.avg_speed_kmh.toFixed(0)} <small>KM/H</small>`;
    document.getElementById('finish-soc').innerHTML = `${msg.final_soc_mj.toFixed(2)} <small>MJ</small>`;

    const best = lapTimes.length ? Math.min(...lapTimes.map(l => l.time_s)) : null;
    document.getElementById('finish-best-lap').innerText = best !== null ? formatLapTime(best) : '--';

    const actionsEl = document.getElementById('finish-actions');
    const counts = msg.action_counts || {};
    actionsEl.innerHTML = Object.entries(counts)
        .sort((a, b) => b[1] - a[1])
        .map(([action, count]) => `<span class="finish-action-chip">${action.split(' -')[0]}: ${count}</span>`)
        .join('');

    // The baseline/Oracle comparison arrives separately as a 'baseline_results' message --
    // each of those is a genuine re-simulated race (see dashboard_server.py's
    // _run_baseline_race), not instant, so this panel is left showing its "Computing
    // baseline metrics..." placeholder (from index.html) until that message lands.
    resetBaselineTable();

    document.getElementById('finish-overlay').classList.add('visible');
}

function resetBaselineTable() {
    const baselineTbody = document.getElementById('baseline-table-body');
    if (baselineTbody) {
        baselineTbody.innerHTML = '<tr><td colspan="3" class="baseline-table-empty">Computing baseline metrics...</td></tr>';
    }
}

function renderBaselineTable(baselines) {
    const baselineTbody = document.getElementById('baseline-table-body');
    if (!baselineTbody || !baselines) return;

    lastBaselineResults = baselines; // kept for the PDF export's baseline-comparison table

    const oracle = baselines.find(b => b.name.includes('Oracle'));
    const oracleTime = oracle ? oracle.time_s : Math.min(...baselines.map(b => b.time_s));

    baselineTbody.innerHTML = baselines.map(b => {
        const isProposed = b.name.includes('Proposed');
        const isOracle = b.name.includes('Oracle');
        const delta = b.time_s - oracleTime;
        const deltaPct = oracleTime > 0 ? (delta / oracleTime) * 100 : 0;

        // delta can be negative (this policy beat the reference row) -- toFixed() doesn't add
        // a '-' of its own for negative numbers the way it silently omits '+' for positive
        // ones, so prefixing a literal '+' unconditionally produced a double sign ("+-4.00s").
        let deltaStr;
        if (Math.abs(delta) < 0.005) {
            deltaStr = "Theoretical Best";
        } else {
            const sign = delta > 0 ? '+' : '-';
            deltaStr = `${sign}${Math.abs(delta).toFixed(2)}s (${sign}${Math.abs(deltaPct).toFixed(1)}%)`;
        }
        const rowClass = isOracle ? 'baseline-row-oracle' : (isProposed ? 'baseline-row-proposed' : '');

        return `
            <tr class="${rowClass}">
                <td>${b.name}</td>
                <td>${formatLapTime(b.time_s)}</td>
                <td>${deltaStr}</td>
            </tr>
        `;
    }).join('');
}

function closeFinishOverlay() {
    document.getElementById('finish-overlay').classList.remove('visible');
}

// --- Documentation overlay ---
function openDocs() {
    document.getElementById('docs-overlay').classList.add('visible');
}

function closeDocs() {
    document.getElementById('docs-overlay').classList.remove('visible');
}

document.getElementById('docs-overlay').addEventListener('click', (e) => {
    if (e.target.id === 'docs-overlay') closeDocs(); // click on the backdrop, not the card itself
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeDocs();
});

// --- Race setup ---
function randomizeSeed() {
    currentSeed = Math.floor(Math.random() * 999999);
    document.getElementById('seed-readout').innerText = currentSeed;
}
randomizeSeed();

// Every piece of UI state a race can leave behind, reset in one place -- used by both
// startRace() (a fresh race shouldn't show leftover numbers from the previous one for the
// ~100ms before the first telemetry message arrives) and resetRace() (previously this only
// cleared the chart data and a handful of text fields, so gauges, flags, the action box, the
// overtake panel, the pause button, and the event timeline all silently kept showing the
// finished race's last values after a reset).
function resetTelemetryUI() {
    timeData.length = 0;
    socData.length = 0;
    eReqData.length = 0;
    historyLog.length = 0;
    timelineEvents.length = 0;
    lastFinishData = null;
    lastBaselineResults = null;
    lapTimes = [];
    energyChart.update();
    renderLapTimes();
    closeFinishOverlay();

    // Playback control
    isPaused = false;
    document.getElementById('btn-pause-label').textContent = 'PAUSE';
    document.getElementById('btn-pause-icon').innerHTML = ICON_PAUSE;

    // Gauges / core telemetry
    document.getElementById('val-lap').innerText = '0 / 0';
    document.getElementById('val-speed').innerText = '0.0';
    document.getElementById('val-soc').innerText = document.getElementById('val-cap').value;
    document.getElementById('val-power').innerText = '0';
    document.getElementById('gauge-speed').style.setProperty('--pct', 0);
    document.getElementById('gauge-soc').style.setProperty('--pct', 100);
    document.getElementById('gauge-soc').classList.remove('gauge-low');

    const fillEl = document.getElementById('power-flow-fill');
    fillEl.style.left = '50%';
    fillEl.style.width = '0%';
    fillEl.classList.remove('regen');

    // Strategy panel
    document.getElementById('val-action').innerText = 'WAITING';
    document.getElementById('val-action').className = 'action-box';
    document.getElementById('val-ereq').innerText = '0.00';
    document.getElementById('val-sige').innerText = '0.00';
    document.getElementById('val-rsafety').innerText = '0.00';
    document.getElementById('val-deployable').innerText = '0.00';
    const robEl = document.getElementById('val-robustness');
    robEl.innerText = 'ROBUSTNESS: HIGH (SAFE)';
    robEl.style.backgroundColor = '';
    robEl.style.color = '';
    robEl.style.borderColor = '';
    document.getElementById('overtake-panel').style.display = 'none';

    // Environment flags -- live on the disturbance buttons themselves now (they double as their
    // own status indicator; see .btn-toggle.active-* in style.css), not a separate flag row.
    document.getElementById('btn-rain').classList.remove('active-rain');
    document.getElementById('btn-sc').classList.remove('active-sc');
    document.getElementById('btn-power').classList.remove('active-power');
    lastFlags = { raining: false, safety_car: false, limited_power: false };
    lastAction = '';

    const timeline = document.getElementById('timeline-container');
    if (timeline) timeline.innerHTML = '<div class="timeline-empty">No events yet</div>';

    resetBaselineTable();

    lastTelemetrySnapshot = null;
    targetTelemetrySnapshot = null;
}

function startRace() {
    if (raceIsActive || !ws || ws.readyState !== WebSocket.OPEN) return;
    resetTelemetryUI();

    const trackClass = document.getElementById('track-class-select').value;
    const laps = parseInt(document.getElementById('laps-select').value, 10);
    ws.send(JSON.stringify({
        command: "start",
        track_class: trackClass,
        laps: laps,
        seed: currentSeed,
    }));
}

function resetRace() {
    resetTelemetryUI();
    raceIsActive = false;
    setStatusPill('connected', 'CONNECTED');
    document.getElementById('btn-start').disabled = false;

    ws.send(JSON.stringify({command: "reset"}));
}

// Icon markup swapped into #btn-pause-icon on each toggle -- the button also holds a separate
// text label (#btn-pause-label), so this can't just be a blanket innerText/innerHTML write on
// the button itself without wiping out the other child.
const ICON_PAUSE = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>';
const ICON_PLAY = '<svg class="icon" width="15" height="15" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>';

let isPaused = false;
function pauseRace() {
    isPaused = !isPaused;
    document.getElementById('btn-pause-label').textContent = isPaused ? 'RESUME' : 'PAUSE';
    document.getElementById('btn-pause-icon').innerHTML = isPaused ? ICON_PLAY : ICON_PAUSE;
    if (raceIsActive) setStatusPill(isPaused ? 'paused' : 'live', isPaused ? 'PAUSED' : 'LIVE');
    ws.send(JSON.stringify({command: "pause"}));
}

function injectRain() { ws.send(JSON.stringify({command: "inject_rain"})); }
function injectSC() { ws.send(JSON.stringify({command: "inject_sc"})); }
function injectPower() { ws.send(JSON.stringify({command: "inject_power"})); }

function setSpeed(value) {
    const multiplier = parseFloat(value);
    ws.send(JSON.stringify({command: "set_speed", value: multiplier}));
}

document.getElementById('speed-select').addEventListener('change', (e) => {
    setSpeed(e.target.value);
});

// Tuning sliders -- each paired with a typable number input (#val-mass etc.) so a precise value
// can be entered directly instead of only ever dragging the slider. The two stay in sync in both
// directions; either one committing a value sends the same 'set_tune' websocket message.
function setupTuning() {
    const params = ['mass', 'cla', 'cap'];
    params.forEach(param => {
        const slider = document.getElementById(`tune-${param}`);
        const input = document.getElementById(`val-${param}`);
        if (!slider || !input) return;

        const decimals = param === 'mass' ? 0 : 2;
        const backendParam = param === 'cap' ? 'capacity' : param;

        function sendTune(value) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ command: 'set_tune', param: backendParam, value }));
            }
        }

        slider.addEventListener('input', (e) => {
            input.value = parseFloat(e.target.value).toFixed(decimals);
        });
        slider.addEventListener('change', (e) => sendTune(e.target.value));

        function commitTypedValue() {
            const min = parseFloat(slider.min);
            const max = parseFloat(slider.max);
            let v = parseFloat(input.value);
            if (Number.isNaN(v)) v = parseFloat(slider.value);
            v = Math.min(max, Math.max(min, v));
            input.value = v.toFixed(decimals);
            slider.value = v;
            sendTune(v);
        }

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') input.blur();
        });
        input.addEventListener('blur', commitTypedValue);
    });
}
setupTuning();

// --- Custom dropdowns ---
// Progressively enhances a native <select> into a glass-panel-styled dropdown that matches the
// rest of the app instead of the browser's default popup. The original <select> is kept in the
// DOM (visually hidden, not display:none, so it's still a real focusable/valid form control) as
// the single source of truth for its value -- every existing piece of code elsewhere in this
// file that reads `select.value` or listens for the select's 'change' event keeps working
// completely unchanged, because a real 'change' Event is dispatched on that same element
// whenever a custom option is picked.
function enhanceSelect(selectId) {
    const select = document.getElementById(selectId);
    if (!select || select.dataset.enhanced) return;
    select.dataset.enhanced = '1';

    const isFull = select.classList.contains('full-select');

    const wrapper = document.createElement('div');
    wrapper.className = 'custom-select' + (isFull ? ' custom-select-full' : '');
    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    select.classList.add('sr-select');

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'custom-select-trigger';
    trigger.innerHTML = '<span class="custom-select-label"></span>' +
        '<svg class="icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>';
    wrapper.appendChild(trigger);

    const panel = document.createElement('div');
    panel.className = 'custom-select-panel';
    wrapper.appendChild(panel);

    const labelEl = trigger.querySelector('.custom-select-label');

    function syncLabel() {
        const opt = select.options[select.selectedIndex];
        labelEl.textContent = opt ? opt.textContent : '';
    }

    function buildOptions() {
        panel.innerHTML = '';
        Array.from(select.options).forEach((opt, idx) => {
            const item = document.createElement('div');
            item.className = 'custom-select-option' + (idx === select.selectedIndex ? ' selected' : '');
            item.textContent = opt.textContent;
            item.addEventListener('click', () => {
                if (select.selectedIndex !== idx) {
                    select.selectedIndex = idx;
                    syncLabel();
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                }
                closePanel();
            });
            panel.appendChild(item);
        });
    }

    function onDocClick(e) {
        if (!wrapper.contains(e.target)) closePanel();
    }

    function openPanel() {
        buildOptions();
        wrapper.classList.add('open');
        document.addEventListener('click', onDocClick);

        // Flip the panel above the trigger when there isn't enough room below it -- e.g. the
        // camera-mode dropdown sits in a pill pinned near the bottom of the viewport, and body
        // has overflow:hidden with no page scroll, so a panel that opened downward there would
        // render partly or entirely past the visible viewport with no way to reach it.
        const triggerRect = trigger.getBoundingClientRect();
        const panelHeight = panel.scrollHeight;
        const spaceBelow = window.innerHeight - triggerRect.bottom;
        const spaceAbove = triggerRect.top;
        wrapper.classList.toggle('drop-up', panelHeight + 12 > spaceBelow && spaceAbove > spaceBelow);
    }

    function closePanel() {
        wrapper.classList.remove('open');
        document.removeEventListener('click', onDocClick);
    }

    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        if (wrapper.classList.contains('open')) closePanel();
        else openPanel();
    });

    syncLabel();
}

['track-class-select', 'laps-select', 'speed-select', 'camera-mode-select'].forEach(enhanceSelect);

// --- Left dock: icon rail + sliding tab drawer ---
let activeTab = null;

function openTab(name) {
    const drawer = document.getElementById('dock-drawer');
    const buttons = document.querySelectorAll('.dock-rail-btn');

    if (activeTab === name) {
        // Clicking the already-open tab collapses the drawer back to just the icon rail.
        drawer.classList.remove('open');
        buttons.forEach(b => b.classList.remove('active'));
        activeTab = null;
        return;
    }

    activeTab = name;
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.tab === name));
    buttons.forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    drawer.classList.add('open');
}

function toggleDock() {
    document.getElementById('dock').classList.toggle('hidden');
}

openTab('setup');

// --- PDF race report export ---
// Renders a Chart.js line chart on a detached offscreen canvas and resolves to a PNG data URL.
// Used instead of screenshotting the live #energyChart canvas because that chart only keeps the
// last 200 samples (capped for render performance -- see historyLog's declaration), while the
// export should cover the whole race.
function renderOfflineChart(data, xLabel, yLabel) {
    return new Promise((resolve) => {
        const canvas = document.createElement('canvas');
        canvas.width = 900;
        canvas.height = 380;
        canvas.style.position = 'fixed';
        canvas.style.left = '-9999px';
        document.body.appendChild(canvas);

        const chart = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data,
            options: {
                responsive: false,
                animation: false,
                plugins: { legend: { labels: { color: '#334155' } } },
                scales: {
                    x: { title: { display: true, text: xLabel, color: '#334155' }, ticks: { color: '#64748b' }, grid: { color: '#e2e8f0' } },
                    y: { title: { display: true, text: yLabel, color: '#334155' }, ticks: { color: '#64748b' }, grid: { color: '#e2e8f0' } },
                },
            },
            plugins: [{
                id: 'whiteBg',
                beforeDraw: (c) => {
                    const chartCtx = c.ctx;
                    chartCtx.save();
                    chartCtx.globalCompositeOperation = 'destination-over';
                    chartCtx.fillStyle = '#ffffff';
                    chartCtx.fillRect(0, 0, c.width, c.height);
                    chartCtx.restore();
                },
            }],
        });

        // Two rAF hops so Chart.js has actually painted the canvas before it's snapshotted --
        // grabbing toDataURL() synchronously right after `new Chart(...)` can catch a blank frame.
        requestAnimationFrame(() => requestAnimationFrame(() => {
            const img = canvas.toDataURL('image/png', 1.0);
            chart.destroy();
            document.body.removeChild(canvas);
            resolve(img);
        }));
    });
}

// Draws the same badge-with-lightning-bolt mark as the header's inline SVG logo, but as native
// jsPDF vector drawing commands rather than a rasterized image -- stays crisp at any zoom/print
// size instead of pixelating, and needs no canvas round-trip to produce.
function drawLogo(doc, x, y, size) {
    const s = size / 32;
    doc.setFillColor(255, 40, 0);
    doc.roundedRect(x, y, size, size, size * 0.22, size * 0.22, 'F');
    doc.setFillColor(255, 255, 255);
    doc.lines(
        [[-9 * s, 14 * s], [6 * s, 0], [-2 * s, 10 * s], [11 * s, -15 * s], [-7 * s, 0]],
        x + 18 * s, y + 4 * s,
        [1, 1],
        'F',
        true
    );
}

async function exportRacePDF() {
    if (historyLog.length === 0 && lapTimes.length === 0) {
        showToast('NO RACE DATA TO EXPORT YET', 'warn');
        return;
    }
    showToast('GENERATING PDF REPORT…', 'info');

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ unit: 'pt', format: 'a4' });
    const pageWidth = doc.internal.pageSize.getWidth();
    const pageHeight = doc.internal.pageSize.getHeight();
    const margin = 40;
    let y = 54;

    const trackClass = document.getElementById('track-class-select').value;
    const laps = document.getElementById('laps-select').value;

    const logoSize = 26;
    drawLogo(doc, margin, y - 20, logoSize);

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(20);
    doc.setTextColor(255, 40, 0);
    doc.text('TrackShift BMS', margin + logoSize + 10, y);
    y += 20;
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(11);
    doc.setTextColor(90, 90, 90);
    const trackLabel = lastFinishData
        ? `${lastFinishData.track_class} · ${lastFinishData.total_laps} lap${lastFinishData.total_laps > 1 ? 's' : ''}`
        : `${trackClass} · ${laps} lap${laps > 1 ? 's' : ''}`;
    doc.text(`${trackLabel}  ·  Seed ${currentSeed}  ·  Generated ${new Date().toLocaleString()}`, margin, y);
    y += 18;
    doc.setDrawColor(225);
    doc.line(margin, y, pageWidth - margin, y);
    y += 26;

    function sectionTitle(text) {
        if (y > pageHeight - 90) { doc.addPage(); y = 54; }
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(13);
        doc.setTextColor(20, 20, 20);
        doc.text(text, margin, y);
        y += 8;
    }

    // Race summary
    sectionTitle('Race Summary');
    const best = lapTimes.length ? Math.min(...lapTimes.map(l => l.time_s)) : null;
    doc.autoTable({
        startY: y,
        margin: { left: margin, right: margin },
        theme: 'plain',
        styles: { fontSize: 10, cellPadding: 4 },
        body: [
            ['Total Time', lastFinishData ? formatLapTime(lastFinishData.total_time_s) : '--'],
            ['Best Lap', best !== null ? formatLapTime(best) : '--'],
            ['Avg Speed', lastFinishData ? `${lastFinishData.avg_speed_kmh.toFixed(1)} km/h` : '--'],
            ['Final SOC', lastFinishData ? `${lastFinishData.final_soc_mj.toFixed(2)} MJ` : '--'],
            ['Laps Completed', `${lapTimes.length}`],
            ['Domain', isFleetMode ? 'EV Delivery Fleet' : 'F1 Motorsport'],
        ],
        columnStyles: { 0: { fontStyle: 'bold', textColor: [90, 90, 90], cellWidth: 140 }, 1: { textColor: [20, 20, 20] } },
    });
    y = doc.lastAutoTable.finalY + 26;

    // Baseline comparison
    if (lastBaselineResults && lastBaselineResults.length) {
        sectionTitle('Performance vs. Baselines');
        const oracle = lastBaselineResults.find(b => b.name.includes('Oracle'));
        const oracleTime = oracle ? oracle.time_s : Math.min(...lastBaselineResults.map(b => b.time_s));
        doc.autoTable({
            startY: y,
            margin: { left: margin, right: margin },
            head: [['Strategy', 'Total Time', 'Delta vs Oracle']],
            body: lastBaselineResults.map((b) => {
                const delta = b.time_s - oracleTime;
                const deltaStr = Math.abs(delta) < 0.005 ? 'Theoretical Best' : `${delta > 0 ? '+' : '-'}${Math.abs(delta).toFixed(2)}s`;
                return [b.name, formatLapTime(b.time_s), deltaStr];
            }),
            styles: { fontSize: 9, cellPadding: 5 },
            headStyles: { fillColor: [15, 23, 42] },
        });
        y = doc.lastAutoTable.finalY + 26;
    }

    // Lap times
    if (lapTimes.length) {
        sectionTitle('Lap Times');
        doc.autoTable({
            startY: y,
            margin: { left: margin, right: margin },
            head: [['Lap', 'Time']],
            body: lapTimes.map(l => [`${l.lap}`, formatLapTime(l.time_s)]),
            styles: { fontSize: 9, cellPadding: 4 },
            headStyles: { fillColor: [15, 23, 42] },
            columnStyles: { 0: { cellWidth: 100 } },
        });
        y = doc.lastAutoTable.finalY + 26;
    }

    // Action breakdown
    if (lastFinishData && lastFinishData.action_counts) {
        sectionTitle('Strategy Action Breakdown');
        doc.autoTable({
            startY: y,
            margin: { left: margin, right: margin },
            head: [['Action', 'Count']],
            body: Object.entries(lastFinishData.action_counts).sort((a, b) => b[1] - a[1]),
            styles: { fontSize: 9, cellPadding: 4 },
            headStyles: { fillColor: [15, 23, 42] },
        });
        y = doc.lastAutoTable.finalY + 26;
    }

    // Event timeline
    if (timelineEvents.length) {
        sectionTitle('Event Timeline');
        doc.autoTable({
            startY: y,
            margin: { left: margin, right: margin },
            head: [['Event']],
            body: timelineEvents.map(e => [e]),
            styles: { fontSize: 9, cellPadding: 4, font: 'courier' },
            headStyles: { fillColor: [15, 23, 42] },
        });
        y = doc.lastAutoTable.finalY + 26;
    }

    // Full-race graphs, rendered fresh from the uncapped historyLog
    if (historyLog.length > 1) {
        doc.addPage();
        y = 54;
        sectionTitle('Energy Profile (Full Race)');
        const energyImg = await renderOfflineChart({
            labels: historyLog.map(h => h.time.toFixed(0)),
            datasets: [
                { label: 'Actual SOC (MJ)', data: historyLog.map(h => h.soc_mj), borderColor: '#ff2800', backgroundColor: 'rgba(255,40,0,0.08)', fill: true, pointRadius: 0, tension: 0.1 },
                { label: 'Predicted Requirement (MJ)', data: historyLog.map(h => h.e_req), borderColor: '#f59e0b', borderDash: [5, 5], pointRadius: 0, tension: 0.1 },
            ],
        }, 'Time (s)', 'Energy (MJ)');
        doc.addImage(energyImg, 'PNG', margin, y + 6, pageWidth - margin * 2, (pageWidth - margin * 2) * (380 / 900));
        y += (pageWidth - margin * 2) * (380 / 900) + 40;

        sectionTitle('Speed Profile (Full Race)');
        const speedImg = await renderOfflineChart({
            labels: historyLog.map(h => h.time.toFixed(0)),
            datasets: [
                { label: 'Speed (km/h)', data: historyLog.map(h => h.velocity_kmh), borderColor: '#38bdf8', backgroundColor: 'rgba(56,189,248,0.08)', fill: true, pointRadius: 0, tension: 0.1 },
            ],
        }, 'Time (s)', 'Speed (km/h)');
        doc.addImage(speedImg, 'PNG', margin, y + 6, pageWidth - margin * 2, (pageWidth - margin * 2) * (380 / 900));
    }

    const safeTrack = (lastFinishData ? lastFinishData.track_class : trackClass).replace(/\s+/g, '_');
    doc.save(`TrackShift-BMS_${safeTrack}_seed${currentSeed}_${Date.now()}.pdf`);
    showToast('PDF REPORT DOWNLOADED', 'good');
}

connect();
