import { useMemo, useRef } from "react";
import { OrbitControls } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

function normalizeLongitude(longitude) {
  let value = Number(longitude);
  while (value > 180) value -= 360;
  while (value < -180) value += 360;
  return value;
}

function unwrapLongitude(longitude, center) {
  let value = Number(longitude);
  while (value - center > 180) value -= 360;
  while (value - center < -180) value += 360;
  return value;
}

function extractGeometry(boundary) {
  if (!boundary) return null;
  if (boundary.type === "Feature") return boundary.geometry ?? null;
  if (boundary.type === "FeatureCollection") return boundary.features?.[0]?.geometry ?? null;
  if (boundary.type === "Polygon" || boundary.type === "MultiPolygon") return boundary;
  if (boundary.geometry) return boundary.geometry;
  if (boundary.boundary?.geometry) return boundary.boundary.geometry;
  if (boundary.boundary?.type) return boundary.boundary;
  if (boundary.geojson?.geometry) return boundary.geojson.geometry;
  if (boundary.geojson?.type === "Polygon" || boundary.geojson?.type === "MultiPolygon") return boundary.geojson;
  return null;
}

function collectPolygons(geometry) {
  if (!geometry?.coordinates) return [];
  if (geometry.type === "Polygon") return [geometry.coordinates];
  if (geometry.type === "MultiPolygon") return geometry.coordinates;
  return [];
}

function getBounds(polygons) {
  const points = polygons
    .flat(2)
    .filter((point) => Array.isArray(point) && point.length >= 2);
  if (!points.length) return null;

  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLon = Infinity;
  let maxLon = -Infinity;

  points.forEach(([lon, lat]) => {
    minLat = Math.min(minLat, Number(lat));
    maxLat = Math.max(maxLat, Number(lat));
    minLon = Math.min(minLon, Number(lon));
    maxLon = Math.max(maxLon, Number(lon));
  });

  return {
    minLat,
    maxLat,
    minLon,
    maxLon,
    centerLat: (minLat + maxLat) / 2,
    centerLon: (minLon + maxLon) / 2,
  };
}

function projectPoint(lon, lat, bounds, width = 7.2, depth = 4.7) {
  const lonCos = Math.max(0.2, Math.cos(THREE.MathUtils.degToRad(bounds.centerLat)));
  const xDegrees = unwrapLongitude(lon, bounds.centerLon) - bounds.centerLon;
  const zDegrees = -(Number(lat) - bounds.centerLat);
  const halfLon = Math.max((bounds.maxLon - bounds.minLon) * lonCos / 2, 0.01);
  const halfLat = Math.max((bounds.maxLat - bounds.minLat) / 2, 0.01);

  return [
    (xDegrees * lonCos / halfLon) * (width / 2),
    (zDegrees / halfLat) * (depth / 2),
  ];
}

function appendRingToShape(target, ring, bounds, width, depth, moveOnly = false) {
  if (!ring || ring.length < 3) return false;
  const points = ring.map(([lon, lat]) => projectPoint(lon, lat, bounds, width, depth));
  points.forEach(([x, z], index) => {
    if (index === 0) target.moveTo(x, z);
    else target.lineTo(x, z);
  });
  if (!moveOnly) target.closePath();
  return true;
}

function makeShape(polygon, bounds, width, depth) {
  const [outer, ...holes] = polygon ?? [];
  if (!outer || outer.length < 3) return null;

  const shape = new THREE.Shape();
  appendRingToShape(shape, outer, bounds, width, depth);
  holes.forEach((ring) => {
    const hole = new THREE.Path();
    if (appendRingToShape(hole, ring, bounds, width, depth)) {
      shape.holes.push(hole);
    }
  });
  return shape;
}

function polygonKey(polygon, index) {
  const first = polygon?.[0]?.[0];
  return `${index}-${first?.[0] ?? 0}-${first?.[1] ?? 0}-${polygon?.[0]?.length ?? 0}`;
}

function BasinMesh({ shape, active, extracted }) {
  const meshRef = useRef(null);
  const target = useRef({ scale: 0.18, y: -0.18, z: 0.15, rotation: -0.72 });

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    const speed = 1 - Math.exp(-3.8 * delta);
    target.current.scale = extracted ? 1 : active ? 0.72 : 0.18;
    target.current.y = extracted ? 0 : -0.18;
    target.current.z = extracted ? 0 : 0.15;
    target.current.rotation = extracted ? -0.62 : -0.82;

    meshRef.current.scale.setScalar(
      THREE.MathUtils.lerp(meshRef.current.scale.x, target.current.scale, speed),
    );
    meshRef.current.position.y = THREE.MathUtils.lerp(meshRef.current.position.y, target.current.y, speed);
    meshRef.current.position.z = THREE.MathUtils.lerp(meshRef.current.position.z, target.current.z, speed);
    meshRef.current.rotation.x = THREE.MathUtils.lerp(meshRef.current.rotation.x, target.current.rotation, speed);
  });

  return (
    <mesh
      ref={meshRef}
      rotation-x={-0.82}
      position={[0, -0.18, 0.15]}
      scale={0.18}
      castShadow
      receiveShadow
    >
      <extrudeGeometry
        args={[
          shape,
          {
            depth: 0.34,
            bevelEnabled: true,
            bevelSegments: 2,
            bevelSize: 0.045,
            bevelThickness: 0.045,
            curveSegments: 2,
          },
        ]}
      />
      <meshPhysicalMaterial
        color="#0d5d78"
        roughness={0.22}
        metalness={0.04}
        transmission={0.08}
        transparent
        opacity={0.9}
      />
    </mesh>
  );
}


function OceanInteractionSurface({ shape, extracted, bounds, width, depth, onHoverCoordinate, onSelectCoordinate, onClearSelection }) {
  const pointerDown = useRef(null);

  const toCoordinate = (event) => {
    if (!event?.point || !bounds) return null;
    const localPoint = event.object.worldToLocal(event.point.clone());
    const lonCos = Math.max(0.2, Math.cos(THREE.MathUtils.degToRad(bounds.centerLat)));
    const halfLon = Math.max((bounds.maxLon - bounds.minLon) * lonCos / 2, 0.01);
    const halfLat = Math.max((bounds.maxLat - bounds.minLat) / 2, 0.01);
    const longitude = bounds.centerLon + (localPoint.x / (width / 2)) * halfLon / lonCos;
    const latitude = bounds.centerLat - (localPoint.y / (depth / 2)) * halfLat;
    return {
      lat: THREE.MathUtils.clamp(latitude, -90, 90),
      lon: normalizeLongitude(longitude),
    };
  };

  const handlePointerMove = (event) => {
    if (!extracted) return;
    const coordinate = toCoordinate(event);
    if (coordinate) onHoverCoordinate?.(coordinate);
  };

  const handlePointerDown = (event) => {
    if (!extracted) return;
    pointerDown.current = { x: event.clientX, y: event.clientY };
  };

  const handlePointerUp = (event) => {
    if (!extracted || !pointerDown.current) return;
    const dx = event.clientX - pointerDown.current.x;
    const dy = event.clientY - pointerDown.current.y;
    pointerDown.current = null;
    if (Math.hypot(dx, dy) > 7) return;

    const coordinate = toCoordinate(event);
    if (coordinate) onSelectCoordinate?.(coordinate);
  };

  return (
    <mesh
      rotation-x={-0.62}
      position={[0, 0.23, 0]}
      onPointerMove={handlePointerMove}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      onPointerCancel={() => { pointerDown.current = null; }}
      visible={extracted}
    >
      <shapeGeometry args={[shape]} />
      <meshBasicMaterial
        transparent
        opacity={0.001}
        depthWrite={false}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}

function WaterSurface({ shape, extracted }) {
  const ref = useRef(null);
  useFrame((state, delta) => {
    if (!ref.current) return;
    const speed = 1 - Math.exp(-3.4 * delta);
    const target = extracted ? 1 : 0.2;
    const next = THREE.MathUtils.lerp(ref.current.scale.x, target, speed);
    ref.current.scale.setScalar(next);
    ref.current.material.opacity = THREE.MathUtils.lerp(ref.current.material.opacity, extracted ? 0.5 : 0.18, speed);
    ref.current.material.emissiveIntensity = 0.3 + Math.sin(state.clock.elapsedTime * 1.7) * 0.06;
  });

  return (
    <mesh ref={ref} rotation-x={-0.62} position={[0, 0.23, 0]} scale={0.2}>
      <shapeGeometry args={[shape]} />
      <meshStandardMaterial
        color="#23a9c7"
        emissive="#0a6680"
        emissiveIntensity={0.3}
        transparent
        opacity={0.18}
        roughness={0.12}
        metalness={0.06}
      />
    </mesh>
  );
}

function SelectedPoint({ coordinate, bounds, extracted }) {
  const ref = useRef(null);
  const point = coordinate && bounds ? projectPoint(coordinate.lon, coordinate.lat, bounds, 7.2, 4.7) : null;

  useFrame((state) => {
    if (!ref.current) return;
    const pulse = 1 + Math.sin(state.clock.elapsedTime * 5) * 0.12;
    ref.current.scale.setScalar(pulse);
  });

  if (!point || !extracted) return null;

  return (
    <group ref={ref} position={[point[0], 0.42, point[1]]}>
      <mesh>
        <sphereGeometry args={[0.075, 18, 18]} />
        <meshBasicMaterial color="#f7f3d2" />
      </mesh>
      <mesh rotation-x={Math.PI / 2}>
        <ringGeometry args={[0.11, 0.135, 32]} />
        <meshBasicMaterial color="#75e8ff" transparent opacity={0.85} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

function BasinFrame({ width = 7.2, depth = 4.7, extracted }) {
  return (
    <mesh rotation-x={-0.62} position={[0, -0.06, 0]}>
      <planeGeometry args={[width + 0.25, depth + 0.25]} />
      <meshBasicMaterial color="#06161f" transparent opacity={extracted ? 0.34 : 0.1} side={THREE.DoubleSide} />
    </mesh>
  );
}

export default function OceanExtraction({
  boundary,
  selectedCoordinate,
  extractionState = "extracting",
  onHoverCoordinate,
  onSelectCoordinate,
  onClearSelection,
}) {
  const extracted = extractionState === "ocean";
  const active = extractionState === "extracting";

  const prepared = useMemo(() => {
    const geometry = extractGeometry(boundary);
    const polygons = collectPolygons(geometry);
    const bounds = getBounds(polygons);
    if (!geometry || !polygons.length || !bounds) return null;

    const width = 7.2;
    const depth = 4.7;
    const shapeEntries = polygons
      .map((polygon, index) => ({ polygon, index, shape: makeShape(polygon, bounds, width, depth) }))
      .filter((entry) => entry.shape);

    return { geometry, polygons, bounds, width, depth, shapeEntries };
  }, [boundary]);

  if (!prepared) {
    return (
      <group>
        <ambientLight intensity={0.45} />
        <directionalLight position={[4, 6, 5]} intensity={2} />
      </group>
    );
  }

  const { bounds, shapeEntries, width, depth } = prepared;
  const outerShapes = shapeEntries;
  const primaryShape = outerShapes[0]?.shape;

  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[4, 6, 5]} intensity={2.1} />
      <directionalLight position={[-4, 1, -5]} intensity={0.5} />

      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.065}
        enablePan
        enableZoom
        minDistance={4.0}
        maxDistance={15}
        rotateSpeed={0.58}
        zoomSpeed={0.8}
        panSpeed={0.52}
        screenSpacePanning
      />

      <group position={[0, -0.05, 0]}>
        <BasinFrame width={width} depth={depth} extracted={extracted} />
        {primaryShape && (
          <OceanInteractionSurface
            shape={primaryShape}
            extracted={extracted}
            bounds={bounds}
            width={width}
            depth={depth}
            onHoverCoordinate={onHoverCoordinate}
            onSelectCoordinate={onSelectCoordinate}
            onClearSelection={onClearSelection}
          />
        )}
        {primaryShape && <WaterSurface shape={primaryShape} extracted={extracted} />}
        {outerShapes.map((entry) => (
          <BasinMesh
            key={polygonKey(entry.polygon, entry.index)}
            shape={entry.shape}
            active={active}
            extracted={extracted}
          />
        ))}
        <SelectedPoint coordinate={selectedCoordinate} bounds={bounds} extracted={extracted} />
      </group>
    </>
  );
}
