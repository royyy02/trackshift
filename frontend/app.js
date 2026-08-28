let ws;
let timeData = [];
let socData = [];
let eReqData = [];
let currentSeed = null;
let lapTimes = []; // [{lap, time_s}]
let raceConfig = { trackClass: 'Balanced', laps: 5 };
let raceIsActive = false;
let isFleetMode = false;

function toggleFleetMode() {
    isFleetMode = document.getElementById('fleet-toggle').checked;
    
    // Update labels to sell the domain transfer
    document.getElementById('mode-label').innerText = isFleetMode ? 'EV DELIVERY FLEET' : 'F1 MOTORSPORT';
    document.querySelector('.brand p').innerText = isFleetMode ? 'FLEET INTELLIGENCE' : 'ENERGY INTELLIGENCE CORE';
    
    // Send command to backend
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ command: "set_mode", mode: isFleetMode ? 'fleet' : 'f1' }));
    }
}

// --- Three.js Setup ---
const trackContainer = document.getElementById('track-container');
const cameraHint = document.getElementById('camera-hint');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf1f5f9); // off-white

const camera = new THREE.PerspectiveCamera(60, trackContainer.clientWidth / trackContainer.clientHeight, 0.1, 20000);
camera.position.set(0, 45, 45);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(trackContainer.clientWidth, trackContainer.clientHeight);
trackContainer.appendChild(renderer.domElement);

// Lighting
const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
scene.add(ambientLight);
const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
dirLight.position.set(0, 100, 50);
scene.add(dirLight);

// Grid Helper for ground
const gridHelper = new THREE.GridHelper(20000, 2000, 0x94a3b8, 0xcbd5e1);
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

let cameraMode = 'orbit'; // 'chase' | 'orbit' | 'free'
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
setCameraMode('orbit');

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

    // Flat black 2D road
    const tubularSegments = Math.min(points.length * 2, 4000);
    const tubeGeo = new THREE.TubeGeometry(trackCurve, tubularSegments, 6, 8, false);
    const tubeMat = new THREE.MeshLambertMaterial({ color: 0x111111, wireframe: false });

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
        } else if (msg.type === 'status') {
            console.log(msg.message);
        }
    };

    ws.onclose = function() {
        setStatusPill('error', 'DISCONNECTED');
        setTimeout(connect, 2000);
    };
}

const MAX_SPEED_KMH = 380; // deployment curve tapers to 0 by 355 km/h (see regulation_config.py)

const MAX_POWER_KW = 350;

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
}

// Called once per telemetry message -- everything here is inherently a discrete/categorical
// state change (lap counter, flag lights, strategy label, chart samples), so there is nothing
// to interpolate; these should still update the instant the server reports them.
function applyDiscreteTelemetry(data) {
    document.getElementById('val-lap').innerText = `${data.lap} / ${data.total_laps}`;

    document.getElementById('flag-rain').classList.toggle('active-rain', data.raining);
    document.getElementById('flag-sc').classList.toggle('active-sc', data.safety_car);
    document.getElementById('flag-power').classList.toggle('active-power', data.limited_power);
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

    // Render baseline comparisons
    const baselineTbody = document.getElementById('baseline-table-body');
    if (baselineTbody && msg.baselines) {
        const oracle = msg.baselines.find(b => b.name.includes('Oracle'));
        const oracleTime = oracle ? oracle.time_s : msg.total_time_s;
        
        baselineTbody.innerHTML = msg.baselines.map(b => {
            const isProposed = b.name.includes('Proposed');
            const delta = b.time_s - oracleTime;
            const deltaPct = (delta / oracleTime) * 100;
            
            let deltaStr = delta === 0 ? "Theoretical Best" : `+${delta.toFixed(2)}s (+${deltaPct.toFixed(1)}%)`;
            let rowStyle = isProposed ? "background: rgba(249, 115, 22, 0.15); color: #fff; font-weight: bold;" : "color: #e2e8f0;";
            if (b.name.includes('Oracle')) rowStyle = "color: var(--accent-green); font-weight: bold;";
            
            return `
                <tr style="border-bottom: 1px solid rgba(255,255,255,0.05); ${rowStyle}">
                    <td style="padding: 8px 4px;">${b.name}</td>
                    <td style="padding: 8px 4px;">${formatLapTime(b.time_s)}</td>
                    <td style="padding: 8px 4px;">${deltaStr}</td>
                </tr>
            `;
        }).join('');
    }

    document.getElementById('finish-overlay').classList.add('visible');
}

function closeFinishOverlay() {
    document.getElementById('finish-overlay').classList.remove('visible');
}

// --- Race setup ---
function randomizeSeed() {
    currentSeed = Math.floor(Math.random() * 999999);
    document.getElementById('seed-readout').innerText = currentSeed;
}
randomizeSeed();

function startRace() {
    if (raceIsActive || !ws || ws.readyState !== WebSocket.OPEN) return;
    timeData.length = 0;
    socData.length = 0;
    eReqData.length = 0;
    lapTimes = [];
    renderLapTimes();
    closeFinishOverlay();

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
    timeData.length = 0;
    socData.length = 0;
    eReqData.length = 0;
    lapTimes = [];
    energyChart.update();
    renderLapTimes();
    closeFinishOverlay();
    raceIsActive = false;
    setStatusPill('connected', 'CONNECTED');

    // Clear UI metrics
    document.getElementById('val-lap').innerText = '0 / 0';
    document.getElementById('val-speed').innerText = '0.0';
    document.getElementById('val-power').innerText = '0';
    document.getElementById('val-action').innerText = 'WAITING';
    document.getElementById('val-action').className = 'action-box';
    document.getElementById('gauge-speed').style.setProperty('--pct', 0);
    document.getElementById('gauge-soc').style.setProperty('--pct', 100);
    document.getElementById('btn-start').disabled = false;
    lastAction = "";
    lastTelemetrySnapshot = null;
    targetTelemetrySnapshot = null;

    ws.send(JSON.stringify({command: "reset"}));
}

let isPaused = false;
function pauseRace() {
    isPaused = !isPaused;
    document.getElementById('btn-pause').innerText = isPaused ? 'RESUME' : 'PAUSE';
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

// Tuning Sliders
function setupTuning() {
    const params = ['mass', 'cla', 'cap'];
    params.forEach(param => {
        const slider = document.getElementById(`tune-${param}`);
        const label = document.getElementById(`val-${param}`);
        if (slider && label) {
            slider.addEventListener('input', (e) => {
                label.innerText = parseFloat(e.target.value).toFixed(param === 'mass' ? 0 : 2);
            });
            slider.addEventListener('change', (e) => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    let backendParam = param;
                    if (param === 'cap') backendParam = 'capacity';
                    ws.send(JSON.stringify({
                        command: 'set_tune',
                        param: backendParam,
                        value: e.target.value
                    }));
                }
            });
        }
    });
}
setupTuning();

function toggleSidebar(side) {
    const el = document.querySelector(`.sidebar-${side}`);
    if (el) {
        el.classList.toggle('collapsed');
        document.body.classList.toggle(`sidebar-${side}-collapsed`);
    }
}

connect();
