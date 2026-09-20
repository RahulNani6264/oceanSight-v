import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";

const W = 7.2;
const D = 4.8;
const TOP = 0.65;
const BOTTOM = -1.55;

function scalarColor(value, min, max) {
  const t = THREE.MathUtils.clamp((value - min) / Math.max(max - min, 1e-9), 0, 1);
  return new THREE.Color().setHSL(0.67 - t * 0.67, 0.85, 0.5);
}

function OceanVolume() {
  return <mesh position={[0, (TOP + BOTTOM) / 2, 0]}>
    <boxGeometry args={[W, TOP - BOTTOM, D]} />
    <meshBasicMaterial color="#123b55" transparent opacity={0.08} depthWrite={false} />
  </mesh>;
}

function Surface() {
  const ref = useRef(null);
  useFrame(({ clock }) => {
    if (ref.current) ref.current.position.y = TOP + Math.sin(clock.getElapsedTime() * 0.7) * 0.02;
  });
  return <mesh ref={ref} position={[0, TOP, 0]} rotation={[-Math.PI / 2, 0, 0]}>
    <planeGeometry args={[W, D, 16, 16]} />
    <meshBasicMaterial color="#278eae" transparent opacity={0.22} side={THREE.DoubleSide} />
  </mesh>;
}

function Grid() {
  const points = useMemo(() => {
    const p = [];
    for (let i = 0; i <= 8; i += 1) {
      const x = -W / 2 + (i / 8) * W;
      p.push([-W / 2, TOP, -D / 2, W / 2, TOP, -D / 2]);
      p.push([x, BOTTOM, -D / 2, x, TOP, -D / 2]);
    }
    return new Float32Array(p.flat());
  }, []);
  return <lineSegments>
    <bufferGeometry><bufferAttribute attach="attributes-position" count={points.length / 3} array={points} itemSize={3} /></bufferGeometry>
    <lineBasicMaterial color="#4d8998" transparent opacity={0.35} />
  </lineSegments>;
}

function InstancedField({ data }) {
  const meshRef = useRef(null);
  const prepared = useMemo(() => {
    const grid = data?.grid;
    const values = grid?.values || [];
    const rows = values.length;
    const cols = rows ? values[0]?.length || 0 : 0;
    if (!rows || !cols) return null;
    const flat = [];
    let min = Infinity;
    let max = -Infinity;
    for (let r = 0; r < rows; r += 1) for (let c = 0; c < cols; c += 1) {
      const v = Number(values[r]?.[c]);
      if (Number.isFinite(v)) { flat.push({ r, c, v }); min = Math.min(min, v); max = Math.max(max, v); }
    }
    if (!flat.length) return null;
    const stride = Math.max(1, Math.ceil(Math.sqrt(flat.length / 3500)));
    const cells = flat.filter((_, i) => i % stride === 0);
    return { rows, cols, cells, min, max };
  }, [data]);

  const geometry = useMemo(() => new THREE.BoxGeometry(W / 64, 0.025, D / 64), []);
  const material = useMemo(() => new THREE.MeshBasicMaterial(), []);
  useMemo(() => {
    if (!meshRef.current || !prepared) return;
    const object = new THREE.Object3D();
    prepared.cells.forEach((cell, i) => {
      object.position.set((cell.c / Math.max(prepared.cols - 1, 1) - 0.5) * W, TOP - 0.08, (cell.r / Math.max(prepared.rows - 1, 1) - 0.5) * D);
      object.scale.set(1, 1, 1);
      object.updateMatrix();
      meshRef.current.setMatrixAt(i, object.matrix);
      meshRef.current.setColorAt(i, scalarColor(cell.v, prepared.min, prepared.max));
    });
    meshRef.current.count = prepared.cells.length;
    meshRef.current.instanceMatrix.needsUpdate = true;
    if (meshRef.current.instanceColor) meshRef.current.instanceColor.needsUpdate = true;
  }, [prepared]);

  if (!prepared) return null;
  return <instancedMesh ref={meshRef} args={[geometry, material, prepared.cells.length]} />;
}

function Badge({ data }) {
  if (!data) return null;
  return <Html position={[-W / 2, TOP + 0.35, 0]}>
    <div style={{ color: "#d9f6ff", background: "rgba(3,18,30,.78)", padding: "6px 9px", borderRadius: 6, fontSize: 11, whiteSpace: "nowrap" }}>
      Live field · {data.variable || data.tile?.variable || "ocean"}
    </div>
  </Html>;
}

export default function OceanScene({ sliceData = null }) {
  return <>
    <OceanVolume />
    <Surface />
    <Grid />
    <InstancedField data={sliceData} />
    <Badge data={sliceData} />
    <OrbitControls enableDamping dampingFactor={0.08} minDistance={4} maxDistance={18} target={[0, -0.35, 0]} />
  </>;
}
