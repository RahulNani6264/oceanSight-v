import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";

function findGrid(source) {
  if (!source || typeof source !== "object") return null;

  const candidates = [
    source.grid,
    source.bathymetry,
    source.data,
    source.field,
    source.result,
    source,
  ];

  for (const candidate of candidates) {
    if (!candidate || typeof candidate !== "object") continue;
    const latitudes = candidate.latitudes || candidate.lats || candidate.latitude || candidate.lat;
    const longitudes = candidate.longitudes || candidate.lons || candidate.longitude || candidate.lon;
    const values = candidate.values || candidate.elevation_m || candidate.depth_m || candidate.elevation || candidate.depth;
    if (Array.isArray(latitudes) && Array.isArray(longitudes) && Array.isArray(values)) {
      return { ...candidate, latitudes, longitudes, values };
    }
  }

  return null;
}

function extractBounds(boundary) {
  const geometry = boundary?.geometry || boundary?.boundary?.geometry || boundary?.boundary || boundary?.geojson || boundary;
  const polygons = [];
  if (!geometry?.coordinates) return null;

  if (geometry.type === "Polygon") polygons.push(geometry.coordinates);
  if (geometry.type === "MultiPolygon") polygons.push(...geometry.coordinates);

  const points = polygons.flatMap((polygon) => polygon[0] || []);
  if (!points.length) return null;

  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  for (const point of points) {
    const lon = Number(point?.[0]);
    const lat = Number(point?.[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    minLon = Math.min(minLon, lon);
    maxLon = Math.max(maxLon, lon);
    minLat = Math.min(minLat, lat);
    maxLat = Math.max(maxLat, lat);
  }
  if (![minLon, maxLon, minLat, maxLat].every(Number.isFinite)) return null;
  return { minLon, maxLon, minLat, maxLat };
}

function flattenNumberGrid(values) {
  if (!Array.isArray(values)) return null;
  if (values.length && Array.isArray(values[0])) return values;

  const dimension = Math.round(Math.sqrt(values.length));
  if (!dimension || dimension * dimension !== values.length) return null;
  return Array.from({ length: dimension }, (_, row) => values.slice(row * dimension, row * dimension + dimension));
}

function finiteRange(grid) {
  let min = Infinity;
  let max = -Infinity;
  for (const row of grid || []) {
    for (const value of row || []) {
      const number = Number(value);
      if (!Number.isFinite(number)) continue;
      min = Math.min(min, number);
      max = Math.max(max, number);
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  if (min === max) max = min + 1;
  return { min, max };
}

function makeGeometry(payload, boundary) {
  const gridSource = findGrid(payload);
  if (!gridSource) return null;

  const latitudes = gridSource.latitudes.map(Number).filter(Number.isFinite);
  const longitudes = gridSource.longitudes.map(Number).filter(Number.isFinite);
  const rawGrid = flattenNumberGrid(gridSource.values);
  if (!latitudes.length || !longitudes.length || !rawGrid?.length) return null;

  const rows = Math.min(latitudes.length, rawGrid.length);
  const cols = Math.min(longitudes.length, rawGrid[0]?.length || 0);
  if (rows < 2 || cols < 2) return null;

  const bathBounds = finiteRange(rawGrid);
  if (!bathBounds) return null;
  const boundaryBounds = extractBounds(boundary);
  const bounds = boundaryBounds || {
    minLon: Math.min(...longitudes),
    maxLon: Math.max(...longitudes),
    minLat: Math.min(...latitudes),
    maxLat: Math.max(...latitudes),
  };

  const width = 7.2;
  const depth = 4.7;
  const xSpan = Math.max(1e-8, bounds.maxLon - bounds.minLon);
  const zSpan = Math.max(1e-8, bounds.maxLat - bounds.minLat);

  const positions = [];
  const values = [];
  const valid = [];

  for (let r = 0; r < rows; r += 1) {
    valid[r] = [];
    for (let c = 0; c < cols; c += 1) {
      const value = Number(rawGrid[r]?.[c]);
      const finite = Number.isFinite(value);
      valid[r][c] = finite;
      const x = ((longitudes[c] - bounds.minLon) / xSpan - 0.5) * width;
      const z = -((latitudes[r] - bounds.minLat) / zSpan - 0.5) * depth;
      const maxAbsDepth = Math.max(1, Math.abs(bathBounds.min), Math.abs(bathBounds.max));
      const normalizedDepth = finite ? Math.min(1, Math.abs(value) / maxAbsDepth) : 0;
      const y = 0.14 - normalizedDepth * 0.92;
      positions.push(x, y, z);
      values.push(finite ? value : 0);
    }
  }

  const indices = [];
  const valueAttribute = [];
  for (let r = 0; r < rows - 1; r += 1) {
    for (let c = 0; c < cols - 1; c += 1) {
      const a = r * cols + c;
      const b = a + 1;
      const d = (r + 1) * cols + c;
      const e = d + 1;
      if (!valid[r][c] && !valid[r][c + 1] && !valid[r + 1][c] && !valid[r + 1][c + 1]) continue;
      indices.push(a, b, e, a, e, d);
      valueAttribute.push(values[a], values[b], values[e], values[a], values[e], values[d]);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();

  return { geometry, range: bathBounds, values: valueAttribute };
}

function depthColor(value, min, max) {
  const t = THREE.MathUtils.clamp((Math.abs(value) - Math.abs(min)) / Math.max(1e-6, Math.abs(max - min)), 0, 1);
  const color = new THREE.Color();
  color.setHSL(0.54 - t * 0.12, 0.78, 0.52 - t * 0.18);
  return color;
}

export default function BathymetryMesh({ payload, boundary = null, visible = true }) {
  const meshRef = useRef(null);

  const prepared = useMemo(() => makeGeometry(payload, boundary), [payload, boundary]);
  const colors = useMemo(() => {
    if (!prepared) return null;
    const { range, values } = prepared;
    const array = new Float32Array(values.length * 3);
    values.forEach((value, index) => {
      const color = depthColor(value, range.min, range.max);
      array[index * 3] = color.r;
      array[index * 3 + 1] = color.g;
      array[index * 3 + 2] = color.b;
    });
    return array;
  }, [prepared]);

  useFrame((state) => {
    if (!meshRef.current) return;
    meshRef.current.material.opacity = THREE.MathUtils.lerp(meshRef.current.material.opacity, visible ? 0.9 : 0, 0.12);
    meshRef.current.position.y = -0.02 + Math.sin(state.clock.elapsedTime * 0.35) * 0.004;
  });

  if (!prepared || !colors) return null;

  prepared.geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

  return (
    <mesh ref={meshRef} geometry={prepared.geometry} rotation-x={-0.62} position={[0, 0, 0]}>
      <meshStandardMaterial
        vertexColors
        transparent
        opacity={visible ? 0.9 : 0}
        roughness={0.36}
        metalness={0.08}
        side={THREE.DoubleSide}
      />
    </mesh>
  );
}
