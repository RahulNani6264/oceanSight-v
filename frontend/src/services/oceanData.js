const VECTOR_VARIABLES = new Set([
  "current_u",
  "current_v",
  "current_speed",
  "current_direction",
  "wind",
]);

function finiteNumber(value) {
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

function getLevel(payload) {
  const data = payload?.data ?? payload;
  if (Array.isArray(data?.levels) && data.levels.length > 0) {
    return data.levels[0];
  }

  const grid = data?.grid;
  if (grid) {
    return {
      ...grid,
      latitudes: grid.latitudes,
      longitudes: grid.longitudes,
      values: grid.values ?? grid.elevation_m,
    };
  }

  return null;
}

function getNamedLevel(payload, names) {
  const levels = payload?.data?.levels ?? payload?.levels;
  if (!Array.isArray(levels)) return null;
  return levels.find((level) => names.includes(level?.output_name)) ?? null;
}

function validateLevel(level, label, payload) {
  if (!level || !Array.isArray(level.latitudes) || !Array.isArray(level.longitudes) || !Array.isArray(level.values)) {
    throw new Error(`${label} response does not contain a usable geographic grid.`);
  }

  const latitudes = level.latitudes.map(finiteNumber);
  const longitudes = level.longitudes.map(finiteNumber);

  if (latitudes.some((value) => value === null) || longitudes.some((value) => value === null)) {
    throw new Error(`${label} response contains invalid latitude or longitude values.`);
  }

  if (latitudes.length === 0 || longitudes.length === 0 || level.values.length !== latitudes.length) {
    throw new Error(`${label} response contains an empty or inconsistent grid.`);
  }

  const validValues = [];
  const hasWaterMask = Array.isArray(level.water_mask) && level.water_mask.some((row) => Array.isArray(row) && row.some(Boolean));
  const values = level.values.map((row, rowIndex) => {
    if (!Array.isArray(row) || row.length !== longitudes.length) {
      throw new Error(`${label} response contains inconsistent array lengths.`);
    }

    return row.map((value, columnIndex) => {
      const missing = level.missing_mask?.[rowIndex]?.[columnIndex] === true;
      const water = level.water_mask?.[rowIndex]?.[columnIndex];
      const numeric = finiteNumber(value);

      if (missing || (hasWaterMask && water === false) || numeric === null) {
        return null;
      }

      validValues.push(numeric);
      return numeric;
    });
  });

  if (validValues.length === 0) {
    throw new Error(`${label} response contains no valid numeric values.`);
  }

  const calculatedRange = getRange(validValues);
  const minimum = finiteNumber(level.minimum ?? level.min ?? payload?.statistics?.minimum) ?? calculatedRange.minimum;
  const maximum = finiteNumber(level.maximum ?? level.max ?? payload?.statistics?.maximum) ?? calculatedRange.maximum;

  return {
    ...level,
    water_mask: hasWaterMask ? level.water_mask : undefined,
    latitudes,
    longitudes,
    values,
    range: {
      minimum,
      maximum: maximum >= minimum ? maximum : minimum,
    },
  };
}

function normalizeSinglePayload(payload, label, preferredLevel = null) {
  const level = validateLevel(preferredLevel ?? getLevel(payload), label, payload);
  return {
    payload: {
      ...payload,
      data: {
        ...(payload?.data ?? {}),
        levels: [level],
      },
    },
    level,
  };
}

export function normalizeOceanData({ payload, variable, vectorPayload = null }) {
  const primaryLevel = variable === "wind"
    ? getNamedLevel(payload, ["wind_speed", "wind_u"])
    : null;
  const primary = normalizeSinglePayload(payload, variable, primaryLevel);
  let vector = null;

  if (VECTOR_VARIABLES.has(variable)) {
    if (variable === "wind") {
      const u = normalizeSinglePayload(payload, "eastward wind", getNamedLevel(payload, ["wind_u"]));
      const v = normalizeSinglePayload(payload, "northward wind", getNamedLevel(payload, ["wind_v"]));
      vector = { u: u.payload, v: v.payload };
    } else {
      if (!vectorPayload?.u || !vectorPayload?.v) {
        throw new Error(`${variable} response is missing both vector components.`);
      }

      const u = normalizeSinglePayload(vectorPayload.u, "eastward current");
      const v = normalizeSinglePayload(vectorPayload.v, "northward current");

      if (u.level.latitudes.length !== v.level.latitudes.length || u.level.longitudes.length !== v.level.longitudes.length) {
        throw new Error(`${variable} response contains incompatible vector grids.`);
      }

      vector = { u: u.payload, v: v.payload };
    }
  }

  return {
    payload: primary.payload,
    vectorPayload: vector,
    level: primary.level,
    range: primary.level.range,
    metadata: {
      providerUpdatedAt: payload?.provider_updated_at ?? payload?.data?.provider_updated_at ?? null,
      serverCachedAt: payload?.server_cached_at ?? payload?.data?.server_cached_at ?? null,
      nextRefreshAt: payload?.next_refresh_at ?? payload?.data?.next_refresh_at ?? null,
      isStale: payload?.is_stale ?? payload?.data?.is_stale ?? false,
      lastError: payload?.last_error ?? payload?.data?.last_error ?? null,
    },
  };
}

export { VECTOR_VARIABLES };
