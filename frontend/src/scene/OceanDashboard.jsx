import {
  useEffect,
  useMemo,
  useState,
} from "react";

import { Canvas } from "@react-three/fiber";
import OceanScene from "./OceanScene";

import {
  OceanSightApiError,
  getHycomTimes,
  getOceanSlice,
} from "../services/api";

// ============================================================================
// REAL HYCOM VARIABLES
// ============================================================================

const HYCOM_VARIABLES = [
  {
    label: "Temperature",
    value: "TEMP",
    unit: "°C",
  },
  {
    label: "Salinity",
    value: "SALN",
    unit: "PSU",
  },
  {
    label: "Eastward Current",
    value: "UVEL",
    unit: "m/s",
  },
  {
    label: "Northward Current",
    value: "VVEL",
    unit: "m/s",
  },
  {
    label: "Sea Surface Height",
    value: "SSH",
    unit: "m",
    surfaceOnly: true,
  },
];

// ============================================================================
// DEPTHS
// ============================================================================

const DEPTH_LEVELS = [
  {
    value: 0,
    label: "Surface",
  },
  {
    value: 10,
    label: "10 m",
  },
  {
    value: 50,
    label: "50 m",
  },
  {
    value: 100,
    label: "100 m",
  },
  {
    value: 250,
    label: "250 m",
  },
  {
    value: 500,
    label: "500 m",
  },
];

// ============================================================================
// FUTURE VARIABLES
// ============================================================================

const FUTURE_VARIABLES = [
  "Pressure",
  "Density",
  "Sound Speed",
  "Dissolved Oxygen",
  "Current Speed",
  "Current Direction",
  "Vertical Velocity",
  "Vorticity",
  "Wave Height",
  "Wave Direction",
  "Wave Period",
  "Wind Speed",
  "Wind Direction",
  "Air Pressure",
  "Chlorophyll-a",
  "Bathymetry",
];

// ============================================================================
// HELPERS
// ============================================================================

function normalizeVariable(variable) {
  if (!variable) {
    return "TEMP";
  }

  const text = String(variable).trim();

  const byValue = HYCOM_VARIABLES.find(
    (item) =>
      item.value.toLowerCase() === text.toLowerCase()
  );

  if (byValue) {
    return byValue.value;
  }

  const byLabel = HYCOM_VARIABLES.find(
    (item) =>
      item.label.toLowerCase() === text.toLowerCase()
  );

  return byLabel?.value ?? "TEMP";
}

function formatCoordinate(value) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return number.toFixed(4);
}

function formatTime(timeUtc) {
  if (!timeUtc) {
    return "—";
  }

  const date = new Date(timeUtc);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

function extractTimes(payload) {
  if (Array.isArray(payload?.times)) {
    return payload.times;
  }

  if (Array.isArray(payload?.catalog)) {
    return payload.catalog;
  }

  if (Array.isArray(payload?.catalog?.times)) {
    return payload.catalog.times;
  }

  return [];
}

// ============================================================================
// OCEAN DASHBOARD
// ============================================================================

export default function OceanDashboard({
  selectedCoordinate = null,
  selectedOcean = null,
  initialVariable = "Temperature",
  enabledOverlays = [],
  onVariableChange,
  onBackToEarth,
}) {
  const [selectedVariable, setSelectedVariable] =
    useState(() => normalizeVariable(initialVariable));

  const [selectedDepth, setSelectedDepth] =
    useState(0);

  const [hycomTimes, setHycomTimes] =
    useState([]);

  const [selectedTimeUtc, setSelectedTimeUtc] =
    useState(null);

  const [timeLoading, setTimeLoading] =
    useState(true);

  const [timeError, setTimeError] =
    useState("");

  const [sliceData, setSliceData] =
    useState(null);

  const [sliceLoading, setSliceLoading] =
    useState(false);

  const [sliceError, setSliceError] =
    useState("");

  const selectedVariableDefinition = useMemo(
    () =>
      HYCOM_VARIABLES.find(
        (item) => item.value === selectedVariable
      ) ?? null,
    [selectedVariable]
  );

  // ==========================================================================
  // LOAD REAL HYCOM TIMES
  // ==========================================================================

  useEffect(() => {
    let cancelled = false;

    async function loadTimes() {
      setTimeLoading(true);
      setTimeError("");

      try {
        const payload = await getHycomTimes();

        if (cancelled) {
          return;
        }

        const records = extractTimes(payload)
          .filter(
            (record) =>
              record &&
              typeof record.time_utc === "string"
          )
          .sort(
            (a, b) =>
              new Date(a.time_utc).getTime() -
              new Date(b.time_utc).getTime()
          );

        setHycomTimes(records);

        if (records.length > 0) {
          setSelectedTimeUtc((current) => {
            const currentExists = records.some(
              (record) => record.time_utc === current
            );

            return currentExists
              ? current
              : records[records.length - 1].time_utc;
          });
        } else {
          setSelectedTimeUtc(null);
          setTimeError(
            "No real HYCOM source timestamps are available."
          );
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        setHycomTimes([]);
        setSelectedTimeUtc(null);

        setTimeError(
          error instanceof OceanSightApiError
            ? error.message
            : error instanceof Error
              ? error.message
              : "Unable to load real HYCOM times."
        );
      } finally {
        if (!cancelled) {
          setTimeLoading(false);
        }
      }
    }

    loadTimes();

    return () => {
      cancelled = true;
    };
  }, []);

  // ==========================================================================
  // LOAD REAL HYCOM SLICE
  // ==========================================================================

  useEffect(() => {
    if (!selectedCoordinate || !selectedTimeUtc) {
      setSliceData(null);
      setSliceLoading(false);
      setSliceError("");
      return;
    }

    let cancelled = false;

    async function loadSlice() {
      setSliceLoading(true);
      setSliceError("");

      const latitude = Number(selectedCoordinate.lat);
      const longitude = Number(selectedCoordinate.lon);

      if (
        !Number.isFinite(latitude) ||
        !Number.isFinite(longitude)
      ) {
        setSliceData(null);
        setSliceError("Selected coordinate is invalid.");
        setSliceLoading(false);
        return;
      }

      const halfWidth = 1.0;

      const latitudeMin = Math.max(
        -90,
        latitude - halfWidth
      );

      const latitudeMax = Math.min(
        90,
        latitude + halfWidth
      );

      const longitudeMin = Math.max(
        -180,
        longitude - halfWidth
      );

      const longitudeMax = Math.min(
        180,
        longitude + halfWidth
      );

      const depth =
        selectedVariable === "SSH"
          ? 0
          : selectedDepth;

      try {
        const payload = await getOceanSlice({
          latitudeMin,
          latitudeMax,
          longitudeMin,
          longitudeMax,
          depthM: depth,
          timeUtc: selectedTimeUtc,
          variable: selectedVariable,
        });

        if (cancelled) {
          return;
        }

        setSliceData(payload);
      } catch (error) {
        if (cancelled) {
          return;
        }

        setSliceData(null);

        setSliceError(
          error instanceof OceanSightApiError
            ? error.message
            : error instanceof Error
              ? error.message
              : "Unable to load real HYCOM slice."
        );
      } finally {
        if (!cancelled) {
          setSliceLoading(false);
        }
      }
    }

    loadSlice();

    return () => {
      cancelled = true;
    };
  }, [
    selectedCoordinate,
    selectedTimeUtc,
    selectedVariable,
    selectedDepth,
  ]);

  // ==========================================================================
  // VARIABLE CHANGE
  // ==========================================================================

  function handleVariableChange(variable) {
    const normalized = normalizeVariable(variable);

    setSelectedVariable(normalized);

    const definition = HYCOM_VARIABLES.find(
      (item) => item.value === normalized
    );

    onVariableChange?.(
      definition?.label ?? normalized
    );

    if (normalized === "SSH") {
      setSelectedDepth(0);
    }
  }

  // ==========================================================================
  // MAIN UI
  // ==========================================================================

  return (
    <section className="ocean-dashboard">
      <header className="ocean-dashboard-header">
        <div className="ocean-dashboard-title-group">
          <div className="ocean-dashboard-eyebrow">
            OCEAN SCIENTIFIC WORKSPACE
          </div>

          <h1 className="ocean-dashboard-title">
            {selectedOcean?.name ?? "Ocean Region"}
          </h1>

          <div className="ocean-dashboard-location">
            <span>LAT</span>

            <strong>
              {formatCoordinate(selectedCoordinate?.lat)}°
            </strong>

            <span>LON</span>

            <strong>
              {formatCoordinate(selectedCoordinate?.lon)}°
            </strong>
          </div>
        </div>

        <button
          type="button"
          className="ocean-dashboard-back-button"
          onClick={onBackToEarth}
        >
          ← Earth
        </button>
      </header>

      <div className="ocean-dashboard-workspace">
        <aside className="ocean-dashboard-panel ocean-dashboard-left">
          <div className="ocean-panel-heading">
            <span>LOCATION</span>
            <span>WHERE?</span>
          </div>

          <div className="ocean-panel-divider" />

          <div className="ocean-coordinate-card">
            <div className="ocean-coordinate-label">
              LATITUDE
            </div>

            <div className="ocean-coordinate-value">
              {formatCoordinate(selectedCoordinate?.lat)}°
            </div>
          </div>

          <div className="ocean-coordinate-card">
            <div className="ocean-coordinate-label">
              LONGITUDE
            </div>

            <div className="ocean-coordinate-value">
              {formatCoordinate(selectedCoordinate?.lon)}°
            </div>
          </div>

          <div className="ocean-coordinate-card">
            <div className="ocean-coordinate-label">
              OCEAN
            </div>

            <div className="ocean-coordinate-value">
              {selectedOcean?.name ?? "UNRESOLVED"}
            </div>
          </div>

          <div className="ocean-context-path">
            <span>EARTH</span>
            <span>→</span>
            <strong>OCEAN</strong>
          </div>
        </aside>

        <main className="ocean-dashboard-center">
          <div className="ocean-scene-container">
            <Canvas
              camera={{
                position: [6.8, 4.5, 7.8],
                fov: 42,
                near: 0.1,
                far: 100,
              }}
              dpr={[1, 1.25]}
              gl={{
                antialias: false,
                powerPreference: "default",
                preserveDrawingBuffer: false,
              }}
              frameloop="always"
            >
              <color
                attach="background"
                args={["#03131f"]}
              />

              <ambientLight intensity={1.2} />

              <directionalLight
                position={[5, 8, 6]}
                intensity={2.2}
              />

              <pointLight
                position={[-4, 2, 4]}
                intensity={1.1}
                color="#4ab6d5"
              />

              <OceanScene
                sliceData={sliceData}
                loading={sliceLoading}
                error={sliceError}
              />
            </Canvas>
          </div>

          <div className="ocean-scene-status">
            <div className="ocean-scene-status-item">
              <span>FIELD</span>

              <strong>
                {selectedVariableDefinition?.label ??
                  selectedVariable}
              </strong>
            </div>

            <div className="ocean-scene-status-item">
              <span>DEPTH</span>

              <strong>
                {selectedVariable === "SSH"
                  ? "SURFACE"
                  : `${selectedDepth} m`}
              </strong>
            </div>

            <div className="ocean-scene-status-item">
              <span>SOURCE TIME</span>

              <strong>
                {formatTime(selectedTimeUtc)}
              </strong>
            </div>
          </div>

          <pre
            className="ocean-debug-data"
            style={{
              maxHeight: "240px",
              overflow: "auto",
              marginTop: "12px",
              padding: "12px",
              borderRadius: "8px",
              background: "#020b12",
              color: "#9ee7ff",
              fontSize: "11px",
              lineHeight: "1.5",
              whiteSpace: "pre-wrap",
            }}
          >
            {sliceData
              ? JSON.stringify(sliceData, null, 2)
              : "No slice data received yet."}
          </pre>
        </main>

        <aside className="ocean-dashboard-panel ocean-dashboard-right">
          <div className="ocean-panel-heading">
            <span>VARIABLES</span>
            <span>WHAT?</span>
          </div>

          <div className="ocean-panel-divider" />

          <div className="ocean-variable-section">
            <div className="ocean-section-label">
              REAL HYCOM FIELDS
            </div>

            {HYCOM_VARIABLES.map((variable) => {
              const active =
                selectedVariable === variable.value;

              return (
                <button
                  type="button"
                  key={variable.value}
                  className={`ocean-variable-button ${
                    active
                      ? "ocean-variable-button-active"
                      : ""
                  }`}
                  onClick={() =>
                    handleVariableChange(variable.value)
                  }
                  aria-pressed={active}
                >
                  <span
                    className={`ocean-variable-dot ${
                      active
                        ? "ocean-variable-dot-active"
                        : ""
                    }`}
                  />

                  <span className="ocean-variable-copy">
                    <span>{variable.label}</span>

                    <small>
                      {variable.unit}

                      {variable.surfaceOnly
                        ? " • surface"
                        : ""}
                    </small>
                  </span>
                </button>
              );
            })}
          </div>

          <div className="ocean-variable-section">
            <div className="ocean-section-label">
              ADDITIONAL FIELDS
            </div>

            {FUTURE_VARIABLES.map((variable) => (
              <div
                key={variable}
                className="ocean-variable-disabled"
                title="Real source not connected yet"
              >
                <span>{variable}</span>
                <span>—</span>
              </div>
            ))}
          </div>

          <div className="ocean-control-section">
            <div className="ocean-panel-heading">
              <span>DEPTH</span>
              <span>HOW DEEP?</span>
            </div>

            <div className="ocean-depth-options">
              {DEPTH_LEVELS.map((depth) => {
                const active =
                  selectedDepth === depth.value;

                const disabled =
                  selectedVariable === "SSH";

                return (
                  <button
                    type="button"
                    key={depth.value}
                    disabled={disabled}
                    className={`ocean-depth-button ${
                      active
                        ? "ocean-depth-button-active"
                        : ""
                    } ${
                      disabled
                        ? "ocean-depth-button-disabled"
                        : ""
                    }`}
                    onClick={() =>
                      setSelectedDepth(depth.value)
                    }
                  >
                    {depth.label}
                  </button>
                );
              })}
            </div>

            {selectedVariable === "SSH" && (
              <div className="ocean-control-note">
                Sea Surface Height is surface-only.
              </div>
            )}
          </div>

          <div className="ocean-control-section">
            <div className="ocean-panel-heading">
              <span>TIME</span>
              <span>WHEN?</span>
            </div>

            {timeError && (
              <div className="ocean-control-error">
                {timeError}
              </div>
            )}

            <div className="ocean-time-current">
              <div className="ocean-time-label">
                EXACT SOURCE TIME
              </div>

              <div className="ocean-time-value">
                {timeLoading
                  ? "Loading real HYCOM times…"
                  : formatTime(selectedTimeUtc)}
              </div>
            </div>

            <div className="ocean-time-list">
              {hycomTimes.map((record, index) => {
                const active =
                  record.time_utc === selectedTimeUtc;

                return (
                  <button
                    type="button"
                    key={`${record.time_utc}-${index}`}
                    className={`ocean-time-button ${
                      active
                        ? "ocean-time-button-active"
                        : ""
                    }`}
                    onClick={() =>
                      setSelectedTimeUtc(record.time_utc)
                    }
                  >
                    <span className="ocean-time-index">
                      {index + 1}
                    </span>

                    <span>
                      {formatTime(record.time_utc)}
                    </span>

                    {active && <span>✓</span>}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="ocean-control-section">
            <div className="ocean-panel-heading">
              <span>FIELD STATUS</span>
            </div>

            <div className="ocean-status-row">
              <span>VARIABLE</span>
              <strong>{selectedVariable}</strong>
            </div>

            <div className="ocean-status-row">
              <span>DATA</span>

              <strong>
                {sliceLoading
                  ? "LOADING"
                  : sliceError
                    ? "ERROR"
                    : sliceData
                      ? "REAL"
                      : "WAITING"}
              </strong>
            </div>

            <div className="ocean-status-row">
              <span>INTERPOLATION</span>

              <strong>
                {sliceData
                  ? sliceData.interpolation === false
                    ? "NO"
                    : "YES"
                  : "—"}
              </strong>
            </div>

            <div className="ocean-status-row">
              <span>SYNTHETIC</span>

              <strong>
                {sliceData
                  ? sliceData.synthetic_data === false
                    ? "NO"
                    : "YES"
                  : "—"}
              </strong>
            </div>

            {sliceError && (
              <div className="ocean-control-error">
                {sliceError}
              </div>
            )}

            {sliceData && (
              <>
                <div className="ocean-status-row">
                  <span>GRID</span>

                  <strong>
                    {sliceData.statistics?.grid_rows ?? "—"}
                    {" × "}
                    {sliceData.statistics?.grid_columns ?? "—"}
                  </strong>
                </div>

                <div className="ocean-status-row">
                  <span>VALID CELLS</span>

                  <strong>
                    {sliceData.statistics?.valid_cells ?? "—"}
                  </strong>
                </div>
              </>
            )}
          </div>

          <div className="ocean-control-section">
            <div className="ocean-panel-heading">
              <span>OBSERVATIONS</span>
            </div>

            {enabledOverlays.length === 0 ? (
              <div className="ocean-control-note">
                No observation overlays selected.
              </div>
            ) : (
              enabledOverlays.map((overlay) => (
                <div
                  key={overlay}
                  className="ocean-status-row"
                >
                  <span>{overlay}</span>
                  <strong>ENABLED</strong>
                </div>
              ))
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}