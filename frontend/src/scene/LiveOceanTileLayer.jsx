import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { getOceanTile } from "../services/api";

const EARTH_RADIUS = 2.35;
const TILE_LEVEL = 2;
const TILE_COUNT_X = 4;
const TILE_COUNT_Y = 2;
const OVERLAY_RADIUS = EARTH_RADIUS + 0.018;

const MAX_COLORS = 16;
const MAX_CACHE_ENTRIES = 64;

const TILE_CACHE = new Map();

const HYCOM_COVERAGE = {
  latitudeMin: -44.929962158203125,
  latitudeMax: 30.9540958404541,
  longitudeMin: 24.020000457763672,
  longitudeMax: 119.83999633789062,
};

const DEFAULT_COLORS = [
  "#313695",
  "#4575b4",
  "#74add1",
  "#abd9e9",
  "#e0f3f8",
  "#ffffbf",
  "#fee090",
  "#fdae61",
  "#f46d43",
  "#d73027",
  "#a50026",
];

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function hexToRgb(hex) {
  const normalized = String(hex || "#ffffff")
    .replace("#", "")
    .trim();

  const value =
    normalized.length === 3
      ? normalized
          .split("")
          .map((character) => `${character}${character}`)
          .join("")
      : normalized;

  const integer = Number.parseInt(value, 16);

  if (!Number.isFinite(integer)) {
    return [1, 1, 1];
  }

  return [
    ((integer >> 16) & 255) / 255,
    ((integer >> 8) & 255) / 255,
    (integer & 255) / 255,
  ];
}

function latitudeLongitudeToVector3(latitude, longitude, radius) {
  const phi = THREE.MathUtils.degToRad(90 - latitude);
  const theta = THREE.MathUtils.degToRad(longitude + 180);

  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  );
}

function readMetadata(buffer) {
  if (!(buffer instanceof ArrayBuffer)) {
    throw new Error("Ocean tile response is not an ArrayBuffer.");
  }

  if (buffer.byteLength < 8) {
    throw new Error("Ocean tile response is too small.");
  }

  const dataView = new DataView(buffer);
  const metadataLength = Number(dataView.getBigUint64(0, true));

  const metadataStart = 8;
  const metadataEnd = metadataStart + metadataLength;

  if (
    !Number.isFinite(metadataLength) ||
    metadataLength <= 0 ||
    metadataEnd > buffer.byteLength
  ) {
    throw new Error("Ocean tile metadata length is invalid.");
  }

  const metadataBytes = new Uint8Array(
    buffer,
    metadataStart,
    metadataLength,
  );

  const metadataText = new TextDecoder("utf-8").decode(metadataBytes);

  let metadata;

  try {
    metadata = JSON.parse(metadataText);
  } catch (error) {
    throw new Error("Ocean tile metadata is not valid JSON.");
  }

  return {
    metadata,
    valuesOffset: metadataEnd,
  };
}

function getTileDimensions(metadata) {
  const tileSize = metadata?.tile_size;

  const rows = Number(
    tileSize?.height ??
      metadata?.height ??
      metadata?.rows ??
      metadata?.ny ??
      metadata?.shape?.[0] ??
      metadata?.dimensions?.[0] ??
      metadata?.grid_shape?.[0] ??
      metadata?.data_shape?.[0] ??
      metadata?.grid?.height ??
      metadata?.grid?.rows,
  );

  const columns = Number(
    tileSize?.width ??
      metadata?.width ??
      metadata?.columns ??
      metadata?.cols ??
      metadata?.nx ??
      metadata?.shape?.[1] ??
      metadata?.dimensions?.[1] ??
      metadata?.grid_shape?.[1] ??
      metadata?.data_shape?.[1] ??
      metadata?.grid?.width ??
      metadata?.grid?.columns,
  );

  if (
    !Number.isInteger(rows) ||
    !Number.isInteger(columns) ||
    rows <= 0 ||
    columns <= 0
  ) {
    throw new Error(
      `Ocean tile dimensions are invalid. Received metadata: ${JSON.stringify(
        metadata,
      )}`,
    );
  }

  return {
    rows,
    columns,
  };
}

function getTileBounds(metadata) {
  const bbox =
    metadata?.bbox ||
    metadata?.bounds ||
    metadata?.tile_bounds ||
    metadata?.tileBounds ||
    {};

  const latitudeMin = Number(
    metadata?.latitude_min ??
      metadata?.lat_min ??
      metadata?.min_lat ??
      bbox?.latitude_min ??
      bbox?.lat_min ??
      bbox?.min_lat ??
      bbox?.south,
  );

  const latitudeMax = Number(
    metadata?.latitude_max ??
      metadata?.lat_max ??
      metadata?.max_lat ??
      bbox?.latitude_max ??
      bbox?.lat_max ??
      bbox?.max_lat ??
      bbox?.north,
  );

  const longitudeMin = Number(
    metadata?.longitude_min ??
      metadata?.lon_min ??
      metadata?.min_lon ??
      bbox?.longitude_min ??
      bbox?.lon_min ??
      bbox?.min_lon ??
      bbox?.west,
  );

  const longitudeMax = Number(
    metadata?.longitude_max ??
      metadata?.lon_max ??
      metadata?.max_lon ??
      bbox?.longitude_max ??
      bbox?.lon_max ??
      bbox?.max_lon ??
      bbox?.east,
  );

  if (
    !Number.isFinite(latitudeMin) ||
    !Number.isFinite(latitudeMax) ||
    !Number.isFinite(longitudeMin) ||
    !Number.isFinite(longitudeMax)
  ) {
    throw new Error(
      `Ocean tile bounds are invalid. Received metadata: ${JSON.stringify(
        metadata,
      )}`,
    );
  }

  return {
    latitudeMin,
    latitudeMax,
    longitudeMin,
    longitudeMax,
  };
}

function getTileRange(tileX, tileY) {
  const longitudeMin =
    -180 + (360 / TILE_COUNT_X) * tileX;

  const longitudeMax =
    -180 + (360 / TILE_COUNT_X) * (tileX + 1);

  const latitudeMax =
    90 - (180 / TILE_COUNT_Y) * tileY;

  const latitudeMin =
    90 - (180 / TILE_COUNT_Y) * (tileY + 1);

  return {
    latitudeMin,
    latitudeMax,
    longitudeMin,
    longitudeMax,
  };
}

function tileOverlapsCoverage(tileX, tileY) {
  const tileBounds = getTileRange(tileX, tileY);

  return (
    tileBounds.latitudeMax >= HYCOM_COVERAGE.latitudeMin &&
    tileBounds.latitudeMin <= HYCOM_COVERAGE.latitudeMax &&
    tileBounds.longitudeMax >= HYCOM_COVERAGE.longitudeMin &&
    tileBounds.longitudeMin <= HYCOM_COVERAGE.longitudeMax
  );
}

function decodeTile(buffer) {
  const { metadata, valuesOffset } = readMetadata(buffer);
  const { rows, columns } = getTileDimensions(metadata);

  const valueCount = rows * columns;
  const valuesByteLength =
    valueCount * Float32Array.BYTES_PER_ELEMENT;

  const maskOffset = valuesOffset + valuesByteLength;

  if (maskOffset + valueCount > buffer.byteLength) {
    throw new Error("Ocean tile payload is truncated.");
  }

  const values = new Float32Array(
    buffer.slice(valuesOffset, maskOffset),
  );

  const mask = new Uint8Array(
    buffer,
    maskOffset,
    valueCount,
  );

  return {
    metadata,
    rows,
    columns,
    values,
    mask,
  };
}

function getColorScale(variableMeta) {
  const candidate =
    variableMeta?.color_scale ||
    variableMeta?.colorScale ||
    variableMeta?.colors ||
    variableMeta?.palette ||
    DEFAULT_COLORS;

  const colors = Array.isArray(candidate)
    ? candidate.filter(Boolean).slice(0, MAX_COLORS)
    : DEFAULT_COLORS;

  return colors.length >= 2 ? colors : DEFAULT_COLORS;
}

function getVariableMinimum(variableMeta, tileMetadata) {
  const value =
    variableMeta?.min ??
    variableMeta?.minimum ??
    variableMeta?.value_range?.min ??
    variableMeta?.range?.min ??
    tileMetadata?.value_range?.min;

  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

function getVariableMaximum(variableMeta, tileMetadata) {
  const value =
    variableMeta?.max ??
    variableMeta?.maximum ??
    variableMeta?.value_range?.max ??
    variableMeta?.range?.max ??
    tileMetadata?.value_range?.max;

  return Number.isFinite(Number(value)) ? Number(value) : 1;
}

function getTimeValue(selectedTimeUtc) {
  if (!selectedTimeUtc) {
    return new Date().toISOString();
  }

  const date = new Date(selectedTimeUtc);

  if (Number.isNaN(date.getTime())) {
    return new Date().toISOString();
  }

  return date.toISOString();
}

function getDepthValue(selectedDepth) {
  if (
    selectedDepth === undefined ||
    selectedDepth === null ||
    selectedDepth === "" ||
    selectedDepth === "surface"
  ) {
    return 0;
  }

  if (selectedDepth === "seafloor") {
    return 0;
  }

  const numericDepth = Number(selectedDepth);

  return Number.isFinite(numericDepth) ? numericDepth : 0;
}

function getTileCacheKey({
  variable,
  timeValue,
  depthValue,
  level,
  tileX,
  tileY,
}) {
  return [
    variable || "sea_surface_height",
    timeValue,
    depthValue,
    level,
    tileX,
    tileY,
  ].join("|");
}

function readCachedTile(cacheKey) {
  const cached = TILE_CACHE.get(cacheKey);

  if (!cached) {
    return null;
  }

  TILE_CACHE.delete(cacheKey);
  TILE_CACHE.set(cacheKey, cached);

  return cached;
}

function writeCachedTile(cacheKey, tile) {
  TILE_CACHE.delete(cacheKey);
  TILE_CACHE.set(cacheKey, tile);

  while (TILE_CACHE.size > MAX_CACHE_ENTRIES) {
    const oldestKey = TILE_CACHE.keys().next().value;

    if (oldestKey === undefined) {
      break;
    }

    TILE_CACHE.delete(oldestKey);
  }
}

function createTileGeometry(tile) {
  const {
    rows,
    columns,
    bounds,
  } = tile;

  const positions = [];
  const uvs = [];
  const indices = [];
  const latitudes = [];

  const {
    latitudeMin,
    latitudeMax,
    longitudeMin,
    longitudeMax,
  } = bounds;

  for (let row = 0; row < rows; row += 1) {
    const rowRatio = rows <= 1 ? 0 : row / (rows - 1);

    const latitude =
      latitudeMin +
      (latitudeMax - latitudeMin) * rowRatio;

    for (let column = 0; column < columns; column += 1) {
      const columnRatio =
        columns <= 1 ? 0 : column / (columns - 1);

      const longitude =
        longitudeMin +
        (longitudeMax - longitudeMin) * columnRatio;

      const point = latitudeLongitudeToVector3(
        latitude,
        longitude,
        OVERLAY_RADIUS,
      );

      positions.push(point.x, point.y, point.z);
      uvs.push(columnRatio, rowRatio);
      latitudes.push(latitude);
    }
  }

  for (let row = 0; row < rows - 1; row += 1) {
    for (let column = 0; column < columns - 1; column += 1) {
      const topLeft = row * columns + column;
      const topRight = topLeft + 1;
      const bottomLeft = (row + 1) * columns + column;
      const bottomRight = bottomLeft + 1;

      indices.push(
        topLeft,
        bottomLeft,
        topRight,
        topRight,
        bottomLeft,
        bottomRight,
      );
    }
  }

  const geometry = new THREE.BufferGeometry();

  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );

  geometry.setAttribute(
    "uv",
    new THREE.Float32BufferAttribute(uvs, 2),
  );

  geometry.setAttribute(
    "latitude",
    new THREE.Float32BufferAttribute(latitudes, 1),
  );

  geometry.setIndex(indices);
  geometry.computeVertexNormals();

  return geometry;
}

function createTileMaterial(tile, variableMeta) {
  const colors = getColorScale(variableMeta);

  const colorValues = colors.map(hexToRgb);

  while (colorValues.length < MAX_COLORS) {
    colorValues.push(colorValues[colorValues.length - 1]);
  }

  const minimum = getVariableMinimum(
    variableMeta,
    tile.metadata,
  );

  const maximum = getVariableMaximum(
    variableMeta,
    tile.metadata,
  );

  const safeMaximum =
    maximum > minimum ? maximum : minimum + 1;

  const colorArray = new Float32Array(
    colorValues.flat(),
  );

  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    uniforms: {
      uValues: {
        value: new THREE.DataTexture(
          new Uint8Array([0, 0, 0, 0]),
          1,
          1,
          THREE.RGBAFormat,
        ),
      },
      uMinimum: {
        value: minimum,
      },
      uMaximum: {
        value: safeMaximum,
      },
      uColorCount: {
        value: colors.length,
      },
      uColors: {
        value: colorArray,
      },
      uRevealLatitude: {
        value: -90,
      },
      uOpacity: {
        value: 1,
      },
    },
    vertexShader: `
      attribute float latitude;

      varying float vLatitude;
      varying vec3 vWorldPosition;

      void main() {
        vLatitude = latitude;
        vWorldPosition = position;

        gl_Position =
          projectionMatrix *
          modelViewMatrix *
          vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      precision highp float;

      uniform sampler2D uValues;
      uniform float uMinimum;
      uniform float uMaximum;
      uniform float uColorCount;
      uniform float uRevealLatitude;
      uniform float uOpacity;

      varying float vLatitude;
      varying vec3 vWorldPosition;

      vec3 colorAt(float normalizedValue) {
        float scaled =
          normalizedValue * (uColorCount - 1.0);

        float lowerIndex = floor(scaled);
        float upperIndex = min(
          lowerIndex + 1.0,
          uColorCount - 1.0
        );

        float blendAmount = fract(scaled);

        vec3 lowerColor = vec3(0.0);
        vec3 upperColor = vec3(0.0);

        for (int index = 0; index < 16; index++) {
          if (float(index) == lowerIndex) {
            lowerColor = vec3(
              0.0,
              0.0,
              0.0
            );
          }
        }

        return mix(lowerColor, upperColor, blendAmount);
      }

      void main() {
        if (vLatitude > uRevealLatitude) {
          discard;
        }

        float longitudeAngle =
          atan(vWorldPosition.z, vWorldPosition.x);

        float latitudeAngle =
          asin(normalize(vWorldPosition).y);

        vec2 lookupUv = vec2(
          (longitudeAngle / 6.28318530718) + 0.5,
          (latitudeAngle / 3.14159265359) + 0.5
        );

        vec4 sampled = texture2D(uValues, lookupUv);

        if (sampled.a < 0.5) {
          discard;
        }

        float value = sampled.r;
        float normalizedValue =
          clamp(
            (value - uMinimum) /
              max(uMaximum - uMinimum, 0.000001),
            0.0,
            1.0
          );

        vec3 coldColor = vec3(0.05, 0.25, 0.65);
        vec3 middleColor = vec3(0.15, 0.85, 0.75);
        vec3 warmColor = vec3(0.95, 0.25, 0.08);

        vec3 color;

        if (normalizedValue < 0.5) {
          color = mix(
            coldColor,
            middleColor,
            normalizedValue * 2.0
          );
        } else {
          color = mix(
            middleColor,
            warmColor,
            (normalizedValue - 0.5) * 2.0
          );
        }

        gl_FragColor = vec4(color, uOpacity);
      }
    `,
  });

  return material;
}

function createTileValueTexture(tile) {
  const {
    rows,
    columns,
    values,
    mask,
  } = tile;

  const pixelCount = rows * columns;
  const rgba = new Uint8Array(pixelCount * 4);

  const minimum = getVariableMinimum(
    tile.variableMeta,
    tile.metadata,
  );

  const maximum = getVariableMaximum(
    tile.variableMeta,
    tile.metadata,
  );

  const safeMaximum =
    maximum > minimum ? maximum : minimum + 1;

  for (let index = 0; index < pixelCount; index += 1) {
    const value = values[index];
    const valid = mask[index] > 0;

    const normalized = valid
      ? clamp(
          (value - minimum) /
            (safeMaximum - minimum),
          0,
          1,
        )
      : 0;

    const byteValue = Math.round(normalized * 255);
    const offset = index * 4;

    rgba[offset] = byteValue;
    rgba[offset + 1] = 0;
    rgba[offset + 2] = 0;
    rgba[offset + 3] = valid ? 255 : 0;
  }

  const texture = new THREE.DataTexture(
    rgba,
    columns,
    rows,
    THREE.RGBAFormat,
    THREE.UnsignedByteType,
  );

  texture.needsUpdate = true;
  texture.flipY = false;
  texture.minFilter = THREE.NearestFilter;
  texture.magFilter = THREE.NearestFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;

  return texture;
}

function createTileMesh(tile, variableMeta) {
  const geometry = createTileGeometry(tile);

  const material = createTileMaterial(
    {
      ...tile,
      variableMeta,
    },
    variableMeta,
  );

  const valueTexture = createTileValueTexture({
    ...tile,
    variableMeta,
  });

  material.uniforms.uValues.value = valueTexture;

  const mesh = new THREE.Mesh(geometry, material);

  mesh.frustumCulled = false;
  mesh.renderOrder = 10;

  mesh.userData.oceanTile = {
    tileX: tile.tileX,
    tileY: tile.tileY,
    variable: tile.variable,
    timeValue: tile.timeValue,
  };

  return mesh;
}

function disposeObject(object) {
  if (!object) {
    return;
  }

  object.traverse((child) => {
    if (child.geometry) {
      child.geometry.dispose();
    }

    if (child.material) {
      const materials = Array.isArray(child.material)
        ? child.material
        : [child.material];

      materials.forEach((material) => {
        if (material.uniforms?.uValues?.value) {
          material.uniforms.uValues.value.dispose();
        }

        material.dispose();
      });
    }
  });
}

function clearGroup(group) {
  if (!group) {
    return;
  }

  while (group.children.length > 0) {
    const child = group.children.pop();
    disposeObject(child);
  }
}

function sortTileRequests(tileRequests) {
  return [...tileRequests].sort((first, second) => {
    const firstRange = getTileRange(
      first.tileX,
      first.tileY,
    );

    const secondRange = getTileRange(
      second.tileX,
      second.tileY,
    );

    const firstLatitude =
      firstRange.latitudeMin;

    const secondLatitude =
      secondRange.latitudeMin;

    if (firstLatitude !== secondLatitude) {
      return firstLatitude - secondLatitude;
    }

    return first.tileX - second.tileX;
  });
}

export default function LiveOceanTileLayer({
  variable = "sea_surface_height",
  variableMeta = null,
  selectedTimeUtc = null,
  selectedDepth = 0,
}) {
  const groupRef = useRef(null);
  const revealFrameRef = useRef(null);
  const revealStartRef = useRef(null);

  const [tiles, setTiles] = useState([]);
  const [loadError, setLoadError] = useState("");

  const timeValue = useMemo(
    () => getTimeValue(selectedTimeUtc),
    [selectedTimeUtc],
  );

  const depthValue = useMemo(
    () => getDepthValue(selectedDepth),
    [selectedDepth],
  );

  useEffect(() => {
    let cancelled = false;

    const controller = new AbortController();

    setTiles([]);
    setLoadError("");

    const tileRequests = [];

    for (let tileY = 0; tileY < TILE_COUNT_Y; tileY += 1) {
      for (let tileX = 0; tileX < TILE_COUNT_X; tileX += 1) {
        if (!tileOverlapsCoverage(tileX, tileY)) {
          continue;
        }

        tileRequests.push({
          tileX,
          tileY,
          variable,
          timeValue,
          depthValue,
          level: TILE_LEVEL,
        });
      }
    }

    const orderedRequests = sortTileRequests(tileRequests);

    async function loadTiles() {
      let successfulTiles = 0;

      for (const request of orderedRequests) {
        if (cancelled) {
          return;
        }

        const cacheKey = getTileCacheKey(request);
        const cachedTile = readCachedTile(cacheKey);

        if (cachedTile) {
          successfulTiles += 1;

          setTiles((currentTiles) => [
            ...currentTiles.filter(
              (tile) =>
                !(
                  tile.tileX === cachedTile.tileX &&
                  tile.tileY === cachedTile.tileY
                ),
            ),
            cachedTile,
          ]);

          continue;
        }

        try {
          const response = await getOceanTile({
            level: request.level,
            x: request.tileX,
            y: request.tileY,
            variable: request.variable,
            time_utc: request.timeValue,
            depth_m: request.depthValue,
            signal: controller.signal,
          });

          if (cancelled) {
            return;
          }

          const decoded = decodeTile(response);

          const tile = {
            ...decoded,
            tileX: request.tileX,
            tileY: request.tileY,
            variable: request.variable,
            timeValue: request.timeValue,
            depthValue: request.depthValue,
            level: request.level,
            bounds: getTileBounds(decoded.metadata),
          };

          writeCachedTile(cacheKey, tile);

          successfulTiles += 1;

          setTiles((currentTiles) => [
            ...currentTiles.filter(
              (currentTile) =>
                !(
                  currentTile.tileX === tile.tileX &&
                  currentTile.tileY === tile.tileY
                ),
            ),
            tile,
          ]);
        } catch (error) {
          if (cancelled || error?.name === "AbortError") {
            return;
          }

          const message = String(error?.message || error);

          if (
            message.includes(
              "does not overlap the available HYCOM coverage",
            )
          ) {
            continue;
          }

          console.warn("[OceanSight] tile request failed", {
            tileX: request.tileX,
            tileY: request.tileY,
            variable: request.variable,
            timeValue: request.timeValue,
            error,
          });
        }
      }

      if (!cancelled && successfulTiles === 0) {
        setLoadError(
          `No ${variable} tiles were available for ${timeValue}.`,
        );
      }
    }

    loadTiles();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [
    variable,
    timeValue,
    depthValue,
  ]);

  useEffect(() => {
    const group = groupRef.current;

    if (!group) {
      return undefined;
    }

    clearGroup(group);

    revealStartRef.current = null;

    if (!tiles.length) {
      return undefined;
    }

    const meshes = tiles
      .slice()
      .sort((first, second) => {
        if (first.tileY !== second.tileY) {
          return first.tileY - second.tileY;
        }

        return first.tileX - second.tileX;
      })
      .map((tile) =>
        createTileMesh(tile, variableMeta),
      );

    meshes.forEach((mesh) => {
      group.add(mesh);
    });

    return () => {
      meshes.forEach((mesh) => {
        if (group.children.includes(mesh)) {
          group.remove(mesh);
        }

        disposeObject(mesh);
      });
    };
  }, [
    tiles,
    variableMeta,
  ]);

  useEffect(() => {
    const group = groupRef.current;

    if (!group || !tiles.length) {
      return undefined;
    }

    revealStartRef.current = null;

    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia?.(
        "(prefers-reduced-motion: reduce)",
      )?.matches;

    if (reducedMotion) {
      group.children.forEach((child) => {
        if (child.material?.uniforms?.uRevealLatitude) {
          child.material.uniforms.uRevealLatitude.value = 90;
        }
      });

      return undefined;
    }

    const duration = 2400;

    function animateReveal(timestamp) {
      if (!revealStartRef.current) {
        revealStartRef.current = timestamp;
      }

      const elapsed =
        timestamp - revealStartRef.current;

      const progress = clamp(
        elapsed / duration,
        0,
        1,
      );

      const easedProgress =
        progress * progress * (3 - 2 * progress);

      const revealLatitude =
        -90 + easedProgress * 180;

      group.children.forEach((child) => {
        if (child.material?.uniforms?.uRevealLatitude) {
          child.material.uniforms.uRevealLatitude.value =
            revealLatitude;
        }
      });

      if (progress < 1) {
        revealFrameRef.current =
          window.requestAnimationFrame(animateReveal);
      } else {
        revealFrameRef.current = null;
      }
    }

    revealFrameRef.current =
      window.requestAnimationFrame(animateReveal);

    return () => {
      if (revealFrameRef.current !== null) {
        window.cancelAnimationFrame(
          revealFrameRef.current,
        );

        revealFrameRef.current = null;
      }
    };
  }, [tiles]);

  useEffect(() => {
    return () => {
      if (revealFrameRef.current !== null) {
        window.cancelAnimationFrame(
          revealFrameRef.current,
        );
      }

      clearGroup(groupRef.current);
    };
  }, []);

  return (
    <group
      ref={groupRef}
      name="live-ocean-tile-layer"
      userData={{
        variable,
        timeValue,
        depthValue,
        tileLevel: TILE_LEVEL,
        tileCount: tiles.length,
        loadError,
      }}
    />
  );
}