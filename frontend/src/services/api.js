const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001";

export class OceanSightApiError extends Error {
  constructor(message, status = null, details = null) {
    super(message);
    this.name = "OceanSightApiError";
    this.status = status;
    this.details = details;
  }
}

function toSnakeCase(value) {
  return value.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
}

function buildQuery(params = {}) {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }

    const backendKey = toSnakeCase(key);

    if (Array.isArray(value)) {
      value.forEach((item) => {
        query.append(backendKey, String(item));
      });
    } else {
      query.set(backendKey, String(value));
    }
  });

  const queryString = query.toString();

  return queryString ? `?${queryString}` : "";
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

async function request(path, options = {}) {
  let response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.body
          ? {
              "Content-Type": "application/json",
            }
          : {}),
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }

    throw new OceanSightApiError(
      `Unable to connect to OceanSight backend at ${API_BASE_URL}`,
      null,
      error,
    );
  }

  const responseText = await response.text();

  let data = null;

  if (responseText) {
    try {
      data = JSON.parse(responseText);
    } catch {
      data = responseText;
    }
  }

  if (!response.ok) {
    let message = `API request failed with status ${response.status}`;

    if (data && typeof data === "object") {
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (Array.isArray(data.detail)) {
        message = data.detail
          .map((item) => item.msg || JSON.stringify(item))
          .join(", ");
      } else if (data.message) {
        message = data.message;
      } else if (data.error) {
        message = data.error;
      }
    } else if (typeof data === "string" && data.trim()) {
      message = data;
    }

    throw new OceanSightApiError(message, response.status, data);
  }

  return data;
}

async function requestBinary(path, options = {}) {
  let response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        Accept: "application/octet-stream",
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }

    throw new OceanSightApiError(
      `Unable to connect to OceanSight backend at ${API_BASE_URL}`,
      null,
      error,
    );
  }

  if (!response.ok) {
    const responseText = await response.text();

    let data = null;

    if (responseText) {
      try {
        data = JSON.parse(responseText);
      } catch {
        data = responseText;
      }
    }

    let message = `Binary API request failed with status ${response.status}`;

    if (data && typeof data === "object") {
      if (typeof data.detail === "string") {
        message = data.detail;
      } else if (data.message) {
        message = data.message;
      } else if (data.error) {
        message = data.error;
      }
    } else if (typeof data === "string" && data.trim()) {
      message = data;
    }

    throw new OceanSightApiError(message, response.status, data);
  }

  return response;
}

export async function getRoot() {
  return request("/");
}

export async function getHealth() {
  return request("/api/v1/health");
}

export async function getHycomTimes(params = {}) {
  return request(`/api/v1/hycom/times${buildQuery(params)}`);
}

export async function getOceanRegions(params = {}) {
  return request(`/api/v1/ocean/regions${buildQuery(params)}`);
}

export async function identifyOcean(latitudeOrParams, longitude) {
  let latitude = latitudeOrParams;
  let resolvedLongitude = longitude;

  if (
    typeof latitudeOrParams === "object" &&
    latitudeOrParams !== null
  ) {
    latitude =
      latitudeOrParams.latitude ??
      latitudeOrParams.lat;

    resolvedLongitude =
      latitudeOrParams.longitude ??
      latitudeOrParams.lon ??
      latitudeOrParams.lng;
  }

  latitude = Number(latitude);
  resolvedLongitude = Number(resolvedLongitude);

  if (
    !Number.isFinite(latitude) ||
    !Number.isFinite(resolvedLongitude)
  ) {
    throw new OceanSightApiError(
      "identifyOcean requires numeric latitude and longitude",
      400,
      {
        latitude,
        longitude: resolvedLongitude,
      },
    );
  }

  return request(
    `/api/v1/ocean/identify${buildQuery({
      latitude,
      longitude: resolvedLongitude,
    })}`,
  );
}

export async function getOceanBoundary(params = {}) {
  return request(
    `/api/v1/ocean/boundary${buildQuery(params)}`,
  );
}

export async function getOceanVariables(params = {}) {
  return request(
    `/api/v1/ocean/variables${buildQuery(params)}`,
  );
}

export async function getOceanVolume(params = {}) {
  return request(
    `/api/v1/ocean/volume${buildQuery(params)}`,
  );
}

export async function getOceanBathymetry(params = {}) {
  return request(
    `/api/v1/ocean/bathymetry${buildQuery(params)}`,
  );
}

export async function getOceanSensors(params = {}) {
  return request(
    `/api/v1/ocean/sensors${buildQuery(params)}`,
  );
}

export async function getOceanSensor(params = {}) {
  return request(
    `/api/v1/ocean/sensor${buildQuery(params)}`,
  );
}

export async function getOceanTimeWindow(params = {}) {
  return request(
    `/api/v1/ocean/time-window${buildQuery(params)}`,
  );
}

export async function getOceanTimeRange(params = {}) {
  return request(
    `/api/v1/ocean/time-range${buildQuery(params)}`,
  );
}

export async function getOceanContext(params = {}) {
  return request(
    `/api/v1/ocean/context${buildQuery(params)}`,
  );
}

export async function getOceanData(params = {}) {
  const { signal, ...queryParams } = params;

  return request(
    `/api/v1/ocean/data${buildQuery(queryParams)}`,
    {
      signal,
    },
  );
}

export async function getOceanTile(params = {}) {
  const query = {
    level: params.level ?? 2,
    x: params.x ?? 2,
    y: params.y ?? 0,
    timeUtc: params.timeUtc ?? params.time_utc,
    variable: params.variable,
    depthM: params.depthM ?? params.depth_m,
  };

  const response = await requestBinary(
    `/api/v1/ocean/tile${buildQuery(query)}`,
    {
      signal: params.signal,
    },
  );

  const buffer = await response.arrayBuffer();

  return {
    buffer,
    response,
    format: response.headers.get("X-OceanSight-Tile-Format"),
    level: response.headers.get("X-OceanSight-Tile-Level"),
    tileX: response.headers.get("X-OceanSight-Tile-X"),
    tileY: response.headers.get("X-OceanSight-Tile-Y"),
  };
}

export async function getHycomPointValue(params = {}) {
  return request(
    `/api/v1/ocean/point${buildQuery(params)}`,
  );
}

export async function getOceanSlice(params = {}) {
  return request(
    `/api/v1/ocean/slice${buildQuery(params)}`,
  );
}

export async function getArgoProfiles(params = {}) {
  return request(
    `/api/v1/argo/profiles${buildQuery(params)}`,
  );
}

export async function getArgoProfile(params = {}) {
  return request(
    `/api/v1/argo/profile${buildQuery(params)}`,
  );
}

export async function postNavigationRoute(payload = {}) {
  return request("/api/v1/navigation/route", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getJson(path, params = {}) {
  return request(`${path}${buildQuery(params)}`);
}

export async function postJson(path, payload = {}) {
  return request(path, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export { API_BASE_URL };