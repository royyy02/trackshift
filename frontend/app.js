let ws;
let timeData = [];
let socData = [];
let eReqData = [];

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

function buildTrack(segments) {
    trackMeshes.forEach(m => scene.remove(m));
    trackMeshes = [];

    let points = [new THREE.Vector3(0, 0, 0)];
    let currentPos = new THREE.Vector3(0, 0, 0);
    let currentAngle = 0;

    trackTotalLength = 0;
    let isLeft = true;

    // Corners are subdivided into many small steps (was 5) so the resulting spline has a
    // smooth, continuously-varying tangent instead of a coarse polyline -- that polygonal
    // tangent noise was the main source of the camera/car jitter through corners, since both
    // the car's heading and the chase camera's offset are derived from curve.getTangentAt().
    const CORNER_STEPS = 24;

    for (let seg of segments) {
        trackTotalLength += seg.length;
        if (seg.radius === -1) {
            // Straight
            currentPos.x += Math.sin(currentAngle) * seg.length;
            currentPos.z += Math.cos(currentAngle) * seg.length;
            points.push(currentPos.clone());
        } else {
            // Corner
            let theta = seg.length / seg.radius;
            let dir = isLeft ? 1 : -1;
            isLeft = !isLeft;

            for (let i = 1; i <= CORNER_STEPS; i++) {
                let stepTheta = currentAngle + (dir * theta * (i / CORNER_STEPS));
                let stepDist = seg.length / CORNER_STEPS;
                currentPos.x += Math.sin(stepTheta) * stepDist;
                currentPos.z += Math.cos(stepTheta) * stepDist;
                points.push(currentPos.clone());
            }
            currentAngle += dir * theta;
        }
    }

    // 'centripetal' parameterization avoids the loops/overshoots that the default
    // parameterization can produce when point spacing is very uneven (straights vs. corners
    // here), which is another source of the previous spline's tangent noise.
    trackCurve = new THREE.CatmullRomCurve3(points, false, 'centripetal');

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
        // Re-sync the server with whatever speed the dropdown is currently set to
        // (e.g. after a reconnect).
        setSpeed(document.getElementById('speed-select').value);
    };

    ws.onmessage = function(event) {
        const msg = JSON.parse(event.data);
        if (msg.type === 'telemetry') {
            if (msg.tick_interval_s) tickIntervalMs = msg.tick_interval_s * 1000;
            updateDashboard(msg);
            update3DView(msg.distance, msg.action);
        } else if (msg.type === 'track_geometry') {
            buildTrack(msg.track);
        } else if (msg.type === 'finished') {
            logEvent("RACE FINISHED");
        } else if (msg.type === 'status') {
            logEvent(msg.message);
        }
    };

    ws.onclose = function() {
        setTimeout(connect, 2000);
    };
}

let lastAction = "";
function updateDashboard(data) {
    document.getElementById('val-lap').innerText = `${data.lap} / ${data.total_laps}`;
    document.getElementById('val-speed').innerText = data.velocity_kmh.toFixed(1);
    document.getElementById('val-soc').innerText = data.soc_mj.toFixed(2);

    let netKw = data.deploy_kw - data.regen_kw;
    document.getElementById('val-power').innerText = netKw.toFixed(0);

    document.getElementById('flag-rain').classList.toggle('active-rain', data.raining);
    document.getElementById('flag-sc').classList.toggle('active-sc', data.safety_car);
    document.getElementById('flag-power').classList.toggle('active-power', data.limited_power);

    const actionEl = document.getElementById('val-action');
    actionEl.innerText = data.action;
    actionEl.className = 'action-box';
    if (data.action.includes("ATTACK")) actionEl.classList.add("action-attack");
    else if (data.action.includes("HARVEST") || data.action.includes("REGEN")) actionEl.classList.add("action-harvest");
    else if (data.action.includes("COAST")) actionEl.classList.add("action-coast");
    else if (data.action.includes("CONSERVE") || data.action.includes("INFEASIBLE")) actionEl.classList.add("action-conserve");

    if (data.action !== lastAction) {
        logEvent(`ACTION CHANGED: ${lastAction || 'NONE'} -> ${data.action}`);
        lastAction = data.action;
    }

    document.getElementById('val-ereq').innerText = data.e_req.toFixed(2);
    document.getElementById('val-sige').innerText = data.sig_e.toFixed(2);
    document.getElementById('val-rsafety').innerText = data.r_safety.toFixed(2);
    document.getElementById('val-deployable').innerText = data.deployable.toFixed(2);

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

function logEvent(text) {
    console.log(text);
}

function startRace() {
    timeData.length = 0;
    socData.length = 0;
    eReqData.length = 0;
    logEvent("RACE STARTED");
    ws.send(JSON.stringify({command: "start"}));
}

function resetRace() {
    timeData.length = 0;
    socData.length = 0;
    eReqData.length = 0;
    energyChart.update();
    logEvent("SIMULATION RESET");
    
    // Clear UI metrics
    document.getElementById('val-lap').innerText = '0 / 0';
    document.getElementById('val-speed').innerText = '0.0';
    document.getElementById('val-power').innerText = '0';
    document.getElementById('val-action').innerText = 'WAITING';
    document.getElementById('val-action').className = 'action-box';
    
    ws.send(JSON.stringify({command: "reset"}));
}

function pauseRace() {
    logEvent("PAUSED/RESUMED");
    ws.send(JSON.stringify({command: "pause"}));
}

function injectRain() { ws.send(JSON.stringify({command: "inject_rain"})); }
function injectSC() { ws.send(JSON.stringify({command: "inject_sc"})); }
function injectPower() { ws.send(JSON.stringify({command: "inject_power"})); }

function setSpeed(value) {
    const multiplier = parseFloat(value);
    ws.send(JSON.stringify({command: "set_speed", value: multiplier}));
    logEvent(`PLAYBACK SPEED SET TO ${multiplier}x`);
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
    }
}

connect();
