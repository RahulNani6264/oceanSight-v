import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";

const DEFAULT_SCALE = [
  "#313695",
  "#4575B4",
  "#74ADD1",
  "#E0F3F8",
  "#FFFFBF",
  "#FDAE61",
  "#F46D43",
  "#A50026",
];
const MAX_RENDER_CELLS = 128;

function finiteValues(matrix) {
  const values = [];

  for (const row of matrix || []) {
    for (const value of row || []) {
      if (
        value !== null &&
        value !== undefined &&
        Number.isFinite(Number(value))
      ) {
        values.push(Number(value));
      }
    }
  }

  return values;
}

function normalizeScale(scale) {
  return Array.isArray(scale) && scale.length >= 2
    ? scale
    : DEFAULT_SCALE;
}

function hexColor(value) {
  const color = new THREE.Color();

  try {
    color.set(value);
  } catch {
    color.set("#6ec8e8");
  }

  return color;
}

function sampleScale(scale, t) {
  const stops = normalizeScale(scale).map(hexColor);
  const clamped = THREE.MathUtils.clamp(t, 0, 1);
  const scaled = clamped * (stops.length - 1);
  const index = Math.min(
    stops.length - 2,
    Math.floor(scaled),
  );
  const local = scaled - index;

  return stops[index]
    .clone()
    .lerp(stops[index + 1], local);
}

function extractLevel(payload) {
  if (!payload) {
    return null;
  }

  const levels =
    payload?.data?.levels ||
    payload?.levels ||
    [];

  if (Array.isArray(levels) && levels.length > 0) {
    return levels[0];
  }

  const grid =
    payload?.data?.grid ||
    payload?.grid;

  if (
    grid?.latitudes &&
    grid?.longitudes &&
    (grid.values || grid.elevation_m)
  ) {
    return {
      latitudes: grid.latitudes,
      longitudes: grid.longitudes,
      values: grid.values || grid.elevation_m,
      water_mask: grid.water_mask,
      missing_mask: grid.missing_mask,
      actual_depth_m: 0,
      units: payload?.variable?.unit || "m",
    };
  }

  return null;
}

function getVectorLevel(payload, key) {
  if (!payload) {
    return null;
  }

  if (payload[key]) {
    return extractLevel(payload[key]);
  }

  return extractLevel(payload);
}

function getMatrixValue(matrix, row, column) {
  const value = matrix?.[row]?.[column];

  if (value === null || value === undefined) {
    return null;
  }

  const number = Number(value);

  return Number.isFinite(number) ? number : null;
}

function getRange(values) {
  let minimum = Infinity;
  let maximum = -Infinity;

  values.forEach((value) => {
    if (value < minimum) minimum = value;
    if (value > maximum) maximum = value;
  });

  return { minimum, maximum };
}

function reduceGrid(level, maxCells = MAX_RENDER_CELLS) {
  const latitudes = (level.latitudes || []).map(Number).filter(Number.isFinite);
  const longitudes = (level.longitudes || []).map(Number).filter(Number.isFinite);
  const values = level.values || [];
  const waterMask = level.water_mask || [];
  const missingMask = level.missing_mask || [];

  if (latitudes.length < 2 || longitudes.length < 2) {
    return null;
  }

  const rowStep = Math.max(1, Math.ceil(latitudes.length / maxCells));
  const columnStep = Math.max(1, Math.ceil(longitudes.length / maxCells));
  const reducedLatitudes = [];
  const reducedLongitudes = [];
  const reducedValues = [];
  const reducedWaterMask = [];
  const reducedMissingMask = [];

  for (let rowStart = 0; rowStart < latitudes.length; rowStart += rowStep) {
    const rowEnd = Math.min(latitudes.length, rowStart + rowStep);
    const rowValues = [];
    const rowWaterMask = [];
    const rowMissingMask = [];

    for (let columnStart = 0; columnStart < longitudes.length; columnStart += columnStep) {
      const columnEnd = Math.min(longitudes.length, columnStart + columnStep);
      const blockValues = [];
      let hasWater = false;

      for (let row = rowStart; row < rowEnd; row += 1) {
        for (let column = columnStart; column < columnEnd; column += 1) {
          if (waterMask?.[row]?.[column] !== false && !missingMask?.[row]?.[column]) {
            hasWater = true;
          }

          const value = getMatrixValue(values, row, column);
          if (value !== null && waterMask?.[row]?.[column] !== false && !missingMask?.[row]?.[column]) {
            blockValues.push(value);
          }
        }
      }

      rowValues.push(blockValues.length ? blockValues.reduce((sum, value) => sum + value, 0) / blockValues.length : null);
      rowWaterMask.push(hasWater);
      rowMissingMask.push(blockValues.length === 0);
    }

    reducedLatitudes.push(latitudes[Math.min(rowStart + Math.floor((rowEnd - rowStart) / 2), latitudes.length - 1)]);
    reducedValues.push(rowValues);
    reducedWaterMask.push(rowWaterMask);
    reducedMissingMask.push(rowMissingMask);
  }

  for (let columnStart = 0; columnStart < longitudes.length; columnStart += columnStep) {
    const columnEnd = Math.min(longitudes.length, columnStart + columnStep);
    reducedLongitudes.push(longitudes[Math.min(columnStart + Math.floor((columnEnd - columnStart) / 2), longitudes.length - 1)]);
  }

  return {
    ...level,
    latitudes: reducedLatitudes,
    longitudes: reducedLongitudes,
    values: reducedValues,
    water_mask: reducedWaterMask,
    missing_mask: reducedMissingMask,
  };
}

function prepareGrid(
  payload,
  scale,
  width = 7.2,
  depth = 4.7,
) {
  const sourceLevel = extractLevel(payload);
  const level = sourceLevel ? reduceGrid(sourceLevel) : null;

  if (!level) {
    return null;
  }

  const latitudes = (level.latitudes || [])
    .map(Number)
    .filter(Number.isFinite);

  const longitudes = (level.longitudes || [])
    .map(Number)
    .filter(Number.isFinite);

  const values = level.values || [];
  const waterMask = level.water_mask || [];
  const missingMask = level.missing_mask || [];

  if (
    latitudes.length < 2 ||
    longitudes.length < 2
  ) {
    return null;
  }

  const latMin = Math.min(...latitudes);
  const latMax = Math.max(...latitudes);
  const lonMin = Math.min(...longitudes);
  const lonMax = Math.max(...longitudes);

  const latSpan = Math.max(
    0.000001,
    latMax - latMin,
  );

  const lonSpan = Math.max(
    0.000001,
    lonMax - lonMin,
  );

  const valid = [];

  for (
    let row = 0;
    row < latitudes.length;
    row += 1
  ) {
    for (
      let column = 0;
      column < longitudes.length;
      column += 1
    ) {
      const value = getMatrixValue(
        values,
        row,
        column,
      );

      if (value === null) {
        continue;
      }

      if (waterMask?.[row]?.[column] === false) {
        continue;
      }

      if (missingMask?.[row]?.[column]) {
        continue;
      }

      valid.push(value);
    }
  }

  if (!valid.length) {
    return null;
  }

  const { minimum: dataMin, maximum: dataMax } = getRange(valid);
  const range = Math.max(
    1e-12,
    dataMax - dataMin,
  );

  const cellLon =
    longitudes.length > 1
      ? Math.abs(longitudes[1] - longitudes[0])
      : lonSpan / 10;

  const cellLat =
    latitudes.length > 1
      ? Math.abs(latitudes[1] - latitudes[0])
      : latSpan / 10;

  const cellWidth = Math.max(
    0.012,
    (cellLon / lonSpan) * width * 1.06,
  );

  const cellDepth = Math.max(
    0.012,
    (cellLat / latSpan) * depth * 1.06,
  );

  const cells = [];

  for (
    let row = 0;
    row < latitudes.length;
    row += 1
  ) {
    for (
      let column = 0;
      column < longitudes.length;
      column += 1
    ) {
      const value = getMatrixValue(
        values,
        row,
        column,
      );

      if (value === null) {
        continue;
      }

      if (waterMask?.[row]?.[column] === false) {
        continue;
      }

      if (missingMask?.[row]?.[column]) {
        continue;
      }

      const x =
        (
          (longitudes[column] - lonMin) /
            lonSpan -
          0.5
        ) * width;

      const z =
        -(
          (latitudes[row] - latMin) /
            latSpan -
          0.5
        ) * depth;

      const normalized =
        (value - dataMin) / range;

      cells.push({
        position: [x, 0.19, z],
        scale: [cellWidth, cellDepth],
        color: sampleScale(
          scale,
          normalized,
        ),
        value,
      });
    }
  }

  return {
    cells,
    min: dataMin,
    max: dataMax,
    latMin,
    latMax,
    lonMin,
    lonMax,
    level,
    width,
    depth,
  };
}

function FieldCells({ grid }) {
  const ref = useRef(null);

  const meshGeometry = useMemo(
    () => new THREE.PlaneGeometry(1, 1),
    [],
  );

  useEffect(() => {
    if (!ref.current) {
      return;
    }

    grid.cells.forEach((cell, index) => {
      const matrix = new THREE.Matrix4();

      matrix.compose(
        new THREE.Vector3(
          cell.position[0],
          cell.position[1],
          cell.position[2],
        ),
        new THREE.Quaternion().setFromEuler(
          new THREE.Euler(-Math.PI / 2, 0, 0),
        ),
        new THREE.Vector3(
          cell.scale[0],
          cell.scale[1],
          1,
        ),
      );

      ref.current.setMatrixAt(index, matrix);
      ref.current.setColorAt(index, cell.color);
    });

    ref.current.instanceMatrix.needsUpdate = true;

    if (ref.current.instanceColor) {
      ref.current.instanceColor.needsUpdate = true;
    }
  }, [grid]);

  useEffect(
    () => () => {
      meshGeometry.dispose();
    },
    [meshGeometry],
  );

  return (
    <instancedMesh
      ref={ref}
      args={[
        meshGeometry,
        undefined,
        grid.cells.length,
      ]}
      frustumCulled={false}
      renderOrder={10}
    >
      <meshBasicMaterial
        transparent
        opacity={0.92}
        side={THREE.DoubleSide}
        toneMapped={false}
        vertexColors
        depthTest={false}
        depthWrite={false}
      />
    </instancedMesh>
  );
}

function FlowParticles({
  payload,
  color = "#dffaff",
  kind = "current",
}) {
  const groupRef = useRef(null);

  const particles = useMemo(() => {
    if (!payload) {
      return [];
    }

    const uLevel = getVectorLevel(payload, "u");
    const vLevel = getVectorLevel(payload, "v");

    const baseLevel =
      uLevel ||
      vLevel ||
      extractLevel(payload);

    if (!baseLevel) {
      return [];
    }

    const latitudes = baseLevel.latitudes || [];
    const longitudes = baseLevel.longitudes || [];

    if (
      !latitudes.length ||
      !longitudes.length
    ) {
      return [];
    }

    const uValues = uLevel?.values || null;
    const vValues = vLevel?.values || null;

    const primaryLevel =
      extractLevel(payload) ||
      uLevel ||
      vLevel;

    const primaryValues =
      primaryLevel?.values || null;

    const totalPoints =
      latitudes.length * longitudes.length;

    const limit = Math.min(
      260,
      totalPoints,
    );

    const stride = Math.max(
      1,
      Math.floor(
        totalPoints / Math.max(1, limit),
      ),
    );

    const points = [];
    let counter = 0;

    for (
      let row = 0;
      row < latitudes.length &&
      points.length < limit;
      row += 1
    ) {
      for (
        let column = 0;
        column < longitudes.length &&
        points.length < limit;
        column += 1
      ) {
        counter += 1;

        if (counter % stride !== 0) {
          continue;
        }

        const primaryValue = getMatrixValue(
          primaryValues,
          row,
          column,
        );

        const u = getMatrixValue(
          uValues,
          row,
          column,
        );

        const v = getMatrixValue(
          vValues,
          row,
          column,
        );

        const speed =
          Number.isFinite(u) &&
          Number.isFinite(v)
            ? Math.hypot(u, v)
            : primaryValue !== null
              ? Math.abs(primaryValue)
              : null;

        if (speed === null) {
          continue;
        }

        points.push({
          row,
          column,
          speed,
          u: u ?? 0,
          v: v ?? 0,
          phase: (row * 17 + column * 31) % 97,
        });
      }
    }

    return points;
  }, [payload]);

  useFrame((state, delta) => {
    if (
      !groupRef.current ||
      !particles.length
    ) {
      return;
    }

    const time = state.clock.elapsedTime;

    groupRef.current.children.forEach(
      (mesh, index) => {
        const particle = particles[index];

        if (!particle) {
          return;
        }

        const pulse =
          0.5 +
          0.5 *
            Math.sin(
              time * 3 + particle.phase,
            );

        const scale =
          kind === "wind"
            ? 0.0032
            : 0.0024;

        mesh.position.x +=
          delta *
          particle.u *
          scale;

        mesh.position.z -=
          delta *
          particle.v *
          scale;

        mesh.position.z +=
          delta *
          0.006 *
          Math.sin(
            time + particle.phase,
          );

        if (mesh.position.x > 3.75) {
          mesh.position.x = -3.75;
        }

        if (mesh.position.x < -3.75) {
          mesh.position.x = 3.75;
        }

        if (mesh.position.z > 2.45) {
          mesh.position.z = -2.45;
        }

        if (mesh.position.z < -2.45) {
          mesh.position.z = 2.45;
        }

        mesh.scale.setScalar(
          0.34 +
            pulse * 0.25 +
            Math.min(
              0.45,
              particle.speed * 0.03,
            ),
        );
      },
    );
  });

  if (!particles.length) {
    return null;
  }

  const level =
    getVectorLevel(payload, "u") ||
    getVectorLevel(payload, "v") ||
    extractLevel(payload);

  const latitudes = level?.latitudes || [];
  const longitudes = level?.longitudes || [];

  if (
    !latitudes.length ||
    !longitudes.length
  ) {
    return null;
  }

  const numericLatitudes = latitudes
    .map(Number)
    .filter(Number.isFinite);

  const numericLongitudes = longitudes
    .map(Number)
    .filter(Number.isFinite);

  if (
    !numericLatitudes.length ||
    !numericLongitudes.length
  ) {
    return null;
  }

  const latMin = Math.min(...numericLatitudes);
  const latMax = Math.max(...numericLatitudes);
  const lonMin = Math.min(...numericLongitudes);
  const lonMax = Math.max(...numericLongitudes);

  const latSpan = Math.max(
    0.000001,
    latMax - latMin,
  );

  const lonSpan = Math.max(
    0.000001,
    lonMax - lonMin,
  );

  return (
    <group ref={groupRef}>
      {particles.map((particle, index) => {
        const latitude = Number(
          latitudes[particle.row],
        );

        const longitude = Number(
          longitudes[particle.column],
        );

        return (
          <mesh
            key={`${particle.row}-${particle.column}-${index}`}
            position={[
              (
                (longitude - lonMin) /
                  lonSpan -
                0.5
              ) * 7.2,
              0.34,
              -(
                (latitude - latMin) /
                  latSpan -
                0.5
              ) * 4.7,
            ]}
          >
            <sphereGeometry args={[0.022, 7, 7]} />
            <meshBasicMaterial
              color={color}
              transparent
              opacity={0.62}
              toneMapped={false}
            />
          </mesh>
        );
      })}
    </group>
  );
}

export default function LiveOceanField({
  payload,
  variable,
  variableMeta,
  vectorPayload = null,
}) {
  const grid = useMemo(
    () =>
      prepareGrid(
        payload,
        variableMeta?.render?.color_scale,
        7.2,
        4.7,
      ),
    [
      payload,
      variableMeta,
    ],
  );

  const isFlow =
    variableMeta?.render?.kind === "vector" ||
    variableMeta?.category === "ocean_current" ||
    [
      "current_u",
      "current_v",
      "current_speed",
      "current_direction",
      "wind",
    ].includes(variable);

  const isWind =
    variableMeta?.id === "wind" ||
    variable === "wind";

  const resolvedVectorPayload =
    vectorPayload ||
    (isFlow ? payload : null);

  if (!grid) {
    return null;
  }

  return (
    <group
      rotation-x={-0.62}
      position={[0, 0.12, 0]}
    >
      <FieldCells grid={grid} />

      {isFlow && resolvedVectorPayload && (
        <FlowParticles
          payload={resolvedVectorPayload}
          kind={isWind ? "wind" : "current"}
        />
      )}
    </group>
  );
}

export {
  prepareGrid,
  extractLevel,
};