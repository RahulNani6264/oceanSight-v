import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import MainGlobe from "./components/MainGlobe";
import OceanExtraction from "./components/OceanExtraction";
import LiveOceanField from "./components/LiveOceanField";
import BathymetryMesh from "./components/BathymetryMesh";
import {
  OceanSightApiError,
  getHycomTimes,
  getOceanBoundary,
  getOceanRegions,
  getOceanVariables,
  getOceanData,
  getOceanBathymetry,
  identifyOcean,
} from "./services/api";

const FALLBACK_OCEANS = [
  "Pacific Ocean",
  "Atlantic Ocean",
  "Indian Ocean",
  "Southern Ocean",
  "Arctic Ocean",
];

const FALLBACK_VARIABLES = [
  { id: "temperature", name: "Temperature", connected: true },
  { id: "salinity", name: "Salinity", connected: true },
  { id: "current_u", name: "Eastward Current", connected: true },
  { id: "current_v", name: "Northward Current", connected: true },
  { id: "current_speed", name: "Current Speed", connected: true },
  { id: "current_direction", name: "Current Direction", connected: true },
  { id: "sea_surface_height", name: "Sea Surface Height", connected: true },
  { id: "bathymetry", name: "Bathymetry", connected: true },
  { id: "wind", name: "Wind", connected: true },
  { id: "air_pressure", name: "Air Pressure", connected: true },
  { id: "chlorophyll", name: "Chlorophyll", connected: true },
];

function normalizeLongitude(value) {
  let longitude = Number(value);
  while (longitude > 180) longitude -= 360;
  while (longitude < -180) longitude += 360;
  return longitude;
}

function normalizeCoordinate(value) {
  if (!value) return null;
  const lat = Number(value.lat ?? value.latitude);
  const lon = Number(value.lon ?? value.longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return { lat, lon: normalizeLongitude(lon) };
}

function formatCoord(value, positive, negative) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const suffix = number === 0 ? "" : number >= 0 ? ` ${positive}` : ` ${negative}`;
  return `${Math.abs(number).toFixed(4)}°${suffix}`;
}

function formatUtc(value, withDate = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    timeZone: "UTC",
    year: withDate ? "numeric" : undefined,
    month: withDate ? "short" : undefined,
    day: withDate ? "2-digit" : undefined,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function parseSearchNumber(value, min, max) {
  const number = Number(value);
  return Number.isFinite(number) && number >= min && number <= max ? number : null;
}

function buildTimeline(records) {
  const valid = records
    .filter((record) => typeof record?.time_utc === "string")
    .map((record) => record.time_utc)
    .sort((a, b) => new Date(a).getTime() - new Date(b).getTime());

  if (!valid.length) return [];

  const anchor = Date.now();
  const nearest = valid.reduce((best, item) => {
    return Math.abs(new Date(item).getTime() - anchor) < Math.abs(new Date(best).getTime() - anchor)
      ? item
      : best;
  }, valid[0]);

  const center = new Date(nearest).getTime();
  const windowed = valid.filter((item) => {
    const time = new Date(item).getTime();
    return time >= center - 24 * 60 * 60 * 1000 && time <= center + 24 * 60 * 60 * 1000;
  });

  return windowed.map((timeUtc) => ({
    timeUtc,
    offsetHours: Math.round((new Date(timeUtc).getTime() - center) / 3600000),
  }));
}

function getBoundaryGeometry(boundaryResponse) {
  if (!boundaryResponse) return null;
  if (boundaryResponse.type === "Feature") return boundaryResponse.geometry ?? null;
  if (boundaryResponse.type === "FeatureCollection") return boundaryResponse.features?.[0]?.geometry ?? null;
  if (boundaryResponse.type === "Polygon" || boundaryResponse.type === "MultiPolygon") return boundaryResponse;
  if (boundaryResponse.geometry) return boundaryResponse.geometry;
  if (boundaryResponse.boundary?.geometry) return boundaryResponse.boundary.geometry;
  if (boundaryResponse.boundary?.type) return boundaryResponse.boundary;
  if (boundaryResponse.geojson?.geometry) return boundaryResponse.geojson.geometry;
  if (boundaryResponse.geojson?.type === "Polygon" || boundaryResponse.geojson?.type === "MultiPolygon") return boundaryResponse.geojson;
  return null;
}

export default function App() {
  const [hoverCoordinate, setHoverCoordinate] = useState(null);
  const [selectedCoordinate, setSelectedCoordinate] = useState(null);
  const [flyToCoordinate, setFlyToCoordinate] = useState(null);

  const [oceans, setOceans] = useState(FALLBACK_OCEANS);
  const [selectedOcean, setSelectedOcean] = useState("");
  const [variables, setVariables] = useState(FALLBACK_VARIABLES);
  const [selectedVariable, setSelectedVariable] = useState("sea_surface_height");

  const [searchLatitude, setSearchLatitude] = useState("");
  const [searchLongitude, setSearchLongitude] = useState("");
  const [searchOcean, setSearchOcean] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [boundaryLoading, setBoundaryLoading] = useState(false);
  const [searchMessage, setSearchMessage] = useState("");
  const [error, setError] = useState("");

  const [workspaceMode, setWorkspaceMode] = useState("earth");
  const [extractionState, setExtractionState] = useState("idle");
  const [oceanBoundary, setOceanBoundary] = useState(null);

  // Derived workspace flags must be declared before any effect that uses them.
  const earthActive = workspaceMode === "earth";
  const extractionActive = workspaceMode === "ocean";

  const [timeRecords, setTimeRecords] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [selectedTime, setSelectedTime] = useState(null);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarStart, setCalendarStart] = useState("");
  const [calendarEnd, setCalendarEnd] = useState("");
  const [activeRole, setActiveRole] = useState("Analyst");
  const [selectedDepth, setSelectedDepth] = useState(0);
  const [liveData, setLiveData] = useState(null);
  const [vectorData, setVectorData] = useState(null);
  const [liveDataLoading, setLiveDataLoading] = useState(false);
  const [liveDataError, setLiveDataError] = useState("");
  const [bathymetryData, setBathymetryData] = useState(null);
  const [bathymetryLoading, setBathymetryLoading] = useState(false);
  const [bathymetryError, setBathymetryError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function loadReferenceData() {
      try {
        const [regionResult, variableResult, timeResult] = await Promise.all([
          getOceanRegions(),
          getOceanVariables(),
          getHycomTimes(),
        ]);

        if (cancelled) return;

        const regionNames = Array.isArray(regionResult?.oceans)
          ? regionResult.oceans.map((item) => item.name).filter(Boolean)
          : [];
        if (regionNames.length) setOceans(regionNames);

        const supportedVariableIds = new Set([
          "temperature", "salinity", "current_u", "current_v",
          "current_speed", "current_direction", "sea_surface_height",
          "bathymetry", "wind", "air_pressure", "chlorophyll",
        ]);

        const variableAliases = {
          temp: "temperature", sst: "temperature",
          sea_surface_temperature: "temperature", salt: "salinity",
          ssh: "sea_surface_height", sea_level: "sea_surface_height",
          uvel: "current_u", eastward_current: "current_u",
          vvel: "current_v", northward_current: "current_v",
          current_velocity: "current_speed", speed: "current_speed",
          direction: "current_direction", wind_speed: "wind",
          chlor_a: "chlorophyll",
        };

        const remoteVariables = Array.isArray(variableResult?.variables)
          ? variableResult.variables.map((item) => {
              const rawId = String(item?.id || "").trim().toLowerCase();
              const id = variableAliases[rawId] || rawId;
              if (!supportedVariableIds.has(id)) return null;
              return {
                ...item,
                id,
                name: item?.name || id,
                connected: item?.connected !== false,
              };
            }).filter(Boolean)
          : [];

        setVariables([
          ...FALLBACK_VARIABLES,
          ...remoteVariables,
        ].filter((item, index, list) =>
          list.findIndex((candidate) => candidate.id === item.id) === index,
        ));

        const records = Array.isArray(timeResult?.catalog?.times)
          ? timeResult.catalog.times
          : [];
        setTimeRecords(records);
        const prepared = buildTimeline(records);
        setTimeline(prepared);
        if (prepared.length) {
          const initial = prepared.reduce((closest, item) =>
            Math.abs(item.offsetHours) < Math.abs(closest.offsetHours) ? item : closest,
          prepared[0]);
          setSelectedTime(initial.timeUtc);
          const centerDate = new Date(initial.timeUtc);
          setCalendarStart(centerDate.toISOString().slice(0, 16));
          setCalendarEnd(new Date(centerDate.getTime() + 24 * 3600000).toISOString().slice(0, 16));
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(
            requestError instanceof OceanSightApiError
              ? requestError.message
              : "Unable to load live dashboard metadata.",
          );
        }
      }
    }
    loadReferenceData();
    return () => {
      cancelled = true;
    };
  }, []);

  const displayedCoordinate = selectedCoordinate ?? hoverCoordinate;
  const selectedTimeIndex = useMemo(
  () => timeline.findIndex((item) => item.timeUtc === selectedTime),
  [timeline, selectedTime],
);

  const selectedVariableMeta = useMemo(
    () => variables.find((item) => item.id === selectedVariable) ?? variables[0],
    [variables, selectedVariable],
  );

  const depthOptions = useMemo(() => {
    const sourceLevels = selectedVariableMeta?.vertical?.real_source_levels_m;
    if (selectedVariableMeta?.vertical?.mode === "seafloor") return ["seafloor"];
    if (selectedVariableMeta?.vertical?.supported && Array.isArray(sourceLevels) && sourceLevels.length) return sourceLevels;
    return [0];
  }, [selectedVariableMeta]);

  useEffect(() => {
    if (!depthOptions.includes(selectedDepth)) {
      setSelectedDepth(depthOptions[0] ?? 0);
    }
  }, [depthOptions, selectedDepth]);

  useEffect(() => {
    if (!extractionActive || !selectedOcean) {
      setBathymetryData(null);
      setBathymetryError("");
      return;
    }

    let cancelled = false;
    async function loadBathymetry() {
      setBathymetryLoading(true);
      setBathymetryError("");
      try {
        const response = await getOceanBathymetry({ ocean: selectedOcean });
        if (!cancelled) setBathymetryData(response);
      } catch (requestError) {
        if (!cancelled) {
          setBathymetryData(null);
          setBathymetryError(requestError instanceof Error ? requestError.message : "Bathymetry request failed.");
        }
      } finally {
        if (!cancelled) setBathymetryLoading(false);
      }
    }
    loadBathymetry();
    return () => { cancelled = true; };
  }, [extractionActive, selectedOcean]);

  useEffect(() => {
    if (!extractionActive || !selectedOcean || !selectedTime || !selectedVariableMeta?.connected) {
      setLiveData(null);
      setVectorData(null);
      return;
    }

    let cancelled = false;
    async function loadLiveField() {
      setLiveDataLoading(true);
      setLiveDataError("");
      try {
        const depth = typeof selectedDepth === "number" ? String(selectedDepth) : "0";
        const primary = await getOceanData({
          mode: "ocean",
          ocean: selectedOcean,
          timeUtc: selectedTime,
          variable: selectedVariable,
          depthsM: depth,
        });
        if (cancelled) return;
        setLiveData(primary);

        if (["current_u", "current_v", "current_speed", "current_direction"].includes(selectedVariable)) {
          const [u, v] = await Promise.all([
            getOceanData({ mode: "ocean", ocean: selectedOcean, timeUtc: selectedTime, variable: "current_u", depthsM: depth }),
            getOceanData({ mode: "ocean", ocean: selectedOcean, timeUtc: selectedTime, variable: "current_v", depthsM: depth }),
          ]);
          if (!cancelled) {
            setVectorData({ u, v });
          }
        } else {
          setVectorData(null);
        }
      } catch (requestError) {
        if (!cancelled) {
          setLiveData(null);
          setVectorData(null);
          setLiveDataError(requestError instanceof Error ? requestError.message : "Live field request failed.");
        }
      } finally {
        if (!cancelled) setLiveDataLoading(false);
      }
    }
    loadLiveField();
    return () => { cancelled = true; };
  }, [extractionActive, selectedOcean, selectedTime, selectedVariable, selectedDepth, selectedVariableMeta]);

  function handleClearSelection() {
    setSelectedCoordinate(null);
    setSearchMessage("");
  }

  function handleSelectCoordinate(coordinate) {
    const normalized = normalizeCoordinate(coordinate);
    if (!normalized) return;
    setSelectedCoordinate(normalized);
    setSearchLatitude(normalized.lat.toFixed(4));
    setSearchLongitude(normalized.lon.toFixed(4));
  }

  function handleHoverCoordinate(coordinate) {
    if (selectedCoordinate) return;
    setHoverCoordinate(normalizeCoordinate(coordinate));
  }

  async function resolveCoordinate(latitude, longitude) {
    const result = await identifyOcean({ latitude, longitude });
    const oceanName = result?.ocean?.name || "";
    if (oceanName) {
      setSelectedOcean(oceanName);
      setSearchOcean(oceanName);
    }
    return oceanName;
  }

  async function handleCoordinateSearch(event) {
    event.preventDefault();
    setSearchLoading(true);
    setError("");
    setSearchMessage("");

    try {
      const latitude = parseSearchNumber(searchLatitude, -90, 90);
      const longitude = parseSearchNumber(searchLongitude, -180, 180);

      if (latitude === null || longitude === null) {
        throw new Error("Enter a valid latitude (-90 to 90) and longitude (-180 to 180).");
      }

      const coordinate = { lat: latitude, lon: normalizeLongitude(longitude) };
      setSelectedCoordinate(coordinate);
      setFlyToCoordinate(coordinate);

      const oceanName = await resolveCoordinate(latitude, longitude);
      setSearchMessage(
        oceanName
          ? `Point resolved to ${oceanName}.`
          : "The selected coordinate could not be mapped to a supported ocean.",
      );
    } catch (requestError) {
      setError(
        requestError instanceof OceanSightApiError || requestError instanceof Error
          ? requestError.message
          : "Coordinate search failed.",
      );
    } finally {
      setSearchLoading(false);
    }
  }

  function handleOceanChoice(value) {
    setSearchOcean(value);
    setSelectedOcean(value);
    setSearchMessage(value ? `${value} selected.` : "");
    setError("");
  }

  async function openOceanWorkspace(oceanName = searchOcean || selectedOcean) {
    if (!oceanName) return;

    setBoundaryLoading(true);
    setError("");
    setSearchMessage("");
    setSelectedOcean(oceanName);
    setSearchOcean(oceanName);

    try {
      const response = await getOceanBoundary({ ocean: oceanName });
      const geometry = getBoundaryGeometry(response);
      if (!geometry?.coordinates) {
        throw new Error(`The backend returned no usable boundary geometry for ${oceanName}.`);
      }

      setOceanBoundary(response);
      setWorkspaceMode("ocean");
      setExtractionState("extracting");
      setSearchMessage(`${oceanName} boundary loaded from the scientific source. Extracting basin…`);

      window.setTimeout(() => {
        setExtractionState("ocean");
        setSearchMessage(`${oceanName} extracted. Real boundary geometry is now the active 3D workspace.`);
      }, 1600);
    } catch (requestError) {
      setError(
        requestError instanceof OceanSightApiError || requestError instanceof Error
          ? requestError.message
          : "Ocean boundary extraction failed.",
      );
    } finally {
      setBoundaryLoading(false);
    }
  }

  function returnToEarth() {
    setWorkspaceMode("earth");
    setExtractionState("idle");
    setSearchMessage("");
  }

  function handleCalendarApply(event) {
    event.preventDefault();
    const start = new Date(calendarStart);
    const end = new Date(calendarEnd);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end < start) {
      setError("Choose a valid start and end time.");
      return;
    }
    const available = timeRecords
      .filter((record) => record?.time_utc)
      .map((record) => record.time_utc)
      .filter((timeUtc) => {
        const timestamp = new Date(timeUtc).getTime();
        return timestamp >= start.getTime() && timestamp <= end.getTime();
      })
      .sort((a, b) => new Date(a).getTime() - new Date(b).getTime());

    if (!available.length) {
      setError("No exact scientific source timestamps are available in that calendar range.");
      return;
    }

    const rebuilt = buildTimeline(available.map((timeUtc) => ({ time_utc: timeUtc })));
    setTimeline(rebuilt);
    setSelectedTime(rebuilt[0]?.timeUtc ?? available[0]);
    setCalendarOpen(false);
    setError("");
  }

  return (
    <div className={`ocean-app workspace-${workspaceMode} extraction-${extractionState}`}>
      <header className="top-nav">
        <div className="brand-lockup">
          <div className="brand-mark"><span /><span /></div>
          <div>
            <div className="brand-name">OCEANSIGHT</div>
            <div className="brand-tag">OCEAN DIGITAL TWIN</div>
          </div>
        </div>

        <nav className="main-nav" aria-label="Primary navigation">
          <button className="nav-link nav-link-active">Explore</button>
          <button className="nav-link">Live Data</button>
          <button className="nav-link">Research</button>
          <button className="nav-link">Tools</button>
        </nav>

        <div className="top-actions">
          <div className="status-pill"><span className="status-dot" /> LIVE</div>
          <select value={activeRole} onChange={(event) => setActiveRole(event.target.value)} className="role-select">
            <option>Analyst</option>
            <option>Fisheries</option>
            <option>Disaster Management</option>
            <option>Logistics</option>
            <option>Navy</option>
          </select>
          <button className="icon-button" aria-label="Settings">⚙</button>
        </div>
      </header>

      <main className="dashboard-canvas">
        <aside className={`control-rail left-rail ${extractionActive && extractionState === "extracting" ? "rail-transition-out" : ""}`}>
          <div className="rail-title-row">
            <div>
              <div className="eyebrow">{earthActive ? "OCEAN DASHBOARD" : "OCEAN WORKSPACE"}</div>
              <h1>{earthActive ? "Explore the oceans" : "Inspect the selected basin"}</h1>
            </div>
            <span className="rail-index">01</span>
          </div>

          <section className="rail-section location-section">
            <div className="section-title"><span>LOCATION</span><span>WHERE</span></div>
            <div className="live-coordinate-card">
              <div className="coordinate-heading">{earthActive ? "CURSOR POSITION" : "SELECTED POINT"}</div>
              <div className="coordinate-grid">
                <div><span>LAT</span><strong>{formatCoord(displayedCoordinate?.lat, "N", "S")}</strong></div>
                <div><span>LON</span><strong>{formatCoord(displayedCoordinate?.lon, "E", "W")}</strong></div>
              </div>
              <div className={`coordinate-state ${selectedCoordinate ? "coordinate-state-selected" : ""}`}>
                <span className="state-led" />
                {selectedCoordinate ? "POINT LOCKED" : earthActive ? "TRACKING CURSOR" : "NO POINT LOCKED"}
              </div>
            </div>

            <form className="search-card" onSubmit={handleCoordinateSearch}>
              <div className="mini-label">SEARCH COORDINATES</div>
              <div className="two-up">
                <label>Latitude<input value={searchLatitude} onChange={(event) => setSearchLatitude(event.target.value)} placeholder="10.0000" /></label>
                <label>Longitude<input value={searchLongitude} onChange={(event) => setSearchLongitude(event.target.value)} placeholder="80.0000" /></label>
              </div>
              <button className="primary-button" type="submit" disabled={searchLoading}>
                {searchLoading ? "RESOLVING…" : "RESOLVE OCEAN"}
                <span>↗</span>
              </button>
            </form>
          </section>

          <section className="rail-section">
            <div className="section-title"><span>OCEAN</span><span>WHAT</span></div>
            <label className="select-field">
              <span>SELECT OCEAN</span>
              <select value={searchOcean || selectedOcean} onChange={(event) => handleOceanChoice(event.target.value)}>
                <option value="">Choose a basin</option>
                {oceans.map((ocean) => <option key={ocean} value={ocean}>{ocean}</option>)}
              </select>
            </label>
            <button className="secondary-button" type="button" onClick={() => openOceanWorkspace()} disabled={!searchOcean || boundaryLoading}>
              {boundaryLoading ? "LOADING REAL BOUNDARY…" : "EXTRACT OCEAN WORKSPACE"} <span>→</span>
            </button>
            {selectedOcean && <div className="resolved-ocean"><span className="mini-ocean-dot" />{selectedOcean}<small>{earthActive ? "Boundary ready for extraction" : "Active scientific basin"}</small></div>}
            {extractionActive && (
              <button type="button" className="back-to-earth-button" onClick={returnToEarth}>← RETURN TO GLOBAL EARTH</button>
            )}
          </section>

          {(searchMessage || error) && (
            <div className={`feedback-box ${error ? "feedback-error" : ""}`}>
              {error || searchMessage}
            </div>
          )}

          {selectedCoordinate && (
            <button type="button" className="clear-button" onClick={handleClearSelection}>Clear point selection</button>
          )}
        </aside>

        <section className="globe-stage">
          <div className="stage-head">
            <div>
              <span className="stage-kicker">{earthActive ? "GLOBAL VIEW" : "OCEAN EXTRACTION"}</span>
              <strong>{selectedOcean || "ALL OCEANS"}</strong>
            </div>
            <div className="stage-tools">
              <span className="source-chip">INCOIS · RECCAP2 · GEBCO</span>
              <span className="view-chip">{earthActive ? "3D EARTH" : "REAL POLYGON + SEABED"}</span>
            </div>
          </div>

          <div className="globe-visual">
            <div className="glow-ring ring-one" />
            <div className="glow-ring ring-two" />

            {earthActive ? (
              <MainGlobe
                onHoverCoordinate={handleHoverCoordinate}
                onSelectCoordinate={handleSelectCoordinate}
                onClearSelection={handleClearSelection}
                selectedCoordinate={selectedCoordinate}
                flyToCoordinate={flyToCoordinate}
                transitionState="idle"
                variable={selectedVariable}
  variableMeta={selectedVariableMeta}
  selectedTimeUtc={selectedTime}
  selectedDepth={selectedDepth}
              />
            ) : (
              <div className="ocean-extraction-shell">
                <CanvasOceanWorkspace
                  boundary={oceanBoundary}
                  selectedCoordinate={selectedCoordinate}
                  extractionState={extractionState}
                  liveData={liveData}
                  variable={selectedVariable}
                  variableMeta={selectedVariableMeta}
                  vectorData={vectorData}
                  bathymetryData={bathymetryData}
                  bathymetryError={bathymetryError}
                  onHoverCoordinate={handleHoverCoordinate}
                  onSelectCoordinate={handleSelectCoordinate}
                  onClearSelection={handleClearSelection}
                />
              </div>
            )}

            <div className="globe-caption">
              {earthActive ? (
                <>
                  <span>MOVE CURSOR TO INSPECT</span>
                  <span>CLICK TO LOCK A COORDINATE</span>
                </>
              ) : (
                <>
                  <span>REAL SOURCE-MASK POLYGON</span>
                  <span>{extractionState === "extracting" ? "EXTRACTING BASIN…" : "BASIN READY FOR 3D SCIENCE"}</span>
                </>
              )}
            </div>
          </div>

          <div className="live-field-status">
            <span className={`live-field-dot ${liveData ? "is-live" : liveDataLoading ? "is-loading" : ""}`} />
            <span>
  {liveDataLoading
    ? "Fetching real source field…"
    : liveDataError
      ? liveDataError
      : earthActive
        ? `${selectedVariableMeta?.name || "Field"} · live binary tiles active`
        : liveData
          ? `${selectedVariableMeta?.name || "Field"} rendered from backend grid`
          : "Select an ocean variable to load the scientific field"}
</span>
          </div>

          <div className="scene-bottom-callout">
            <div><span className="callout-dot" /><span>{earthActive ? "REAL SOURCE DATA" : "REAL OCEAN BOUNDARY"}</span></div>
            <div>{selectedVariableMeta?.name || "Temperature"} · {activeRole.toUpperCase()}</div>
          </div>
        </section>

        <aside className="control-rail right-rail">
          <div className="rail-title-row compact">
            <div>
              <div className="eyebrow">LIVE FIELDS</div>
              <h2>Variables</h2>
            </div>
            <span className="rail-index">02</span>
          </div>

          <section className="rail-section variable-section">
            <div className="section-title"><span>PRIMARY FIELD</span><span>REAL DATA</span></div>
            <div className="variable-stack">
              {variables.map((variable) => {
                const active = variable.id === selectedVariable;
                const connected = variable.connected !== false;
                return (
                  <button
                    key={variable.id}
                    type="button"
                    className={`variable-row ${active ? "variable-row-active" : ""} ${!connected ? "variable-row-muted" : ""}`}
                    onClick={() => setSelectedVariable(variable.id)}
                  >
                    <span className="variable-radio">{active ? "•" : ""}</span>
                    <span className="variable-name">{variable.name}</span>
                    <span className="variable-status">{connected ? "LIVE" : "OFF"}</span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className="rail-section depth-section">
            <div className="section-title"><span>VERTICAL LAYER</span><span>{selectedVariableMeta?.vertical?.supported ? "SOURCE LEVELS" : "SURFACE"}</span></div>
            <div className="depth-stack">
              {depthOptions.map((depth) => {
                const activeDepth = depth === selectedDepth;
                const label = depth === "seafloor" ? "SEAFLOOR" : `${depth} m`;
                return (
                  <button key={String(depth)} type="button" className={`depth-chip ${activeDepth ? "depth-chip-active" : ""}`} onClick={() => setSelectedDepth(depth)}>
                    {label}
                  </button>
                );
              })}
            </div>
          </section>

          <section className="rail-section scientific-state">
            <div className="section-title"><span>SCIENTIFIC STATE</span><span>NOW</span></div>
            <div className="metric-row"><span>FIELD</span><strong>{selectedVariableMeta?.name || "Temperature"}</strong></div>
            <div className="metric-row"><span>TIME</span><strong>{formatUtc(selectedTime, true)}</strong></div>
            <div className="metric-row"><span>MODE</span><strong>{earthActive ? "GLOBAL OCEAN" : "SELECTED OCEAN"}</strong></div>
            <div className="metric-row"><span>LAYER</span><strong>{selectedDepth === "seafloor" ? "SEAFLOOR" : `${selectedDepth} m`}</strong></div>
            <div className="metric-row">
  <span>FIELD LOAD</span>
  <strong>
    {liveDataLoading
      ? "FETCHING…"
      : liveDataError
        ? "ERROR"
        : earthActive
          ? "LIVE TILES"
          : liveData
            ? "LIVE GRID"
            : "READY"}
  </strong>
</div>
            <div className="metric-row"><span>SEABED</span><strong>{bathymetryLoading ? "FETCHING…" : bathymetryData ? "GEBCO READY" : bathymetryError ? "ERROR" : "READY"}</strong></div>
          </section>

          <button type="button" className={`next-action ${extractionActive ? "next-action-active" : ""}`} disabled={!selectedOcean || boundaryLoading} onClick={() => openOceanWorkspace()}>
            {extractionActive ? "REFRESH OCEAN BOUNDARY" : "CONTINUE TO OCEAN 3D"} <span>→</span>
          </button>
        </aside>
      </main>

      <footer className="time-dock">
        <div className="time-summary">
          <span className="time-label">TIME NAVIGATION</span>
          <strong>{formatUtc(selectedTime, true)}</strong>
          <span className="time-mode">LIVE SOURCE</span>
        </div>

        <div className="timeline-core">
          <button
            className="time-step-button"
            type="button"
            disabled={selectedTimeIndex <= 0}
            onClick={() => setSelectedTime(timeline[selectedTimeIndex - 1]?.timeUtc)}
          >
            ‹
          </button>

          <div className="timeline-track">
            {timeline.length ? (
              timeline.map((item) => (
                <button
                  key={item.timeUtc}
                  type="button"
                  className={`timeline-item ${item.timeUtc === selectedTime ? "timeline-item-active" : ""}`}
                  onClick={() => setSelectedTime(item.timeUtc)}
                  title={new Date(item.timeUtc).toLocaleString(undefined, {
                    timeZone: "UTC",
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                  })}
                >
                  <span>{new Date(item.timeUtc).toLocaleString(undefined, {
                    timeZone: "UTC",
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: false,
                  })}</span>
                </button>
              ))
            ) : (
              <div className="timeline-empty">Loading scientific source times…</div>
            )}
          </div>

          <button
            className="time-step-button"
            type="button"
            disabled={selectedTimeIndex < 0 || selectedTimeIndex >= timeline.length - 1}
            onClick={() => setSelectedTime(timeline[selectedTimeIndex + 1]?.timeUtc)}
          >
            ›
          </button>
        </div>

        <div className="calendar-wrap">
          <button className={`calendar-button ${calendarOpen ? "calendar-button-active" : ""}`} type="button" onClick={() => setCalendarOpen((value) => !value)} aria-label="Open calendar range">▣</button>
          {calendarOpen && (
            <form className="calendar-popover" onSubmit={handleCalendarApply}>
              <div className="calendar-title">SCIENTIFIC RANGE</div>
              <label>START<input type="datetime-local" value={calendarStart} onChange={(event) => setCalendarStart(event.target.value)} /></label>
              <label>END<input type="datetime-local" value={calendarEnd} onChange={(event) => setCalendarEnd(event.target.value)} /></label>
              <button type="submit" className="primary-button">APPLY RANGE</button>
            </form>
          )}
        </div>
      </footer>
    </div>
  );
}

function CanvasOceanWorkspace({
  boundary,
  selectedCoordinate,
  extractionState,
  liveData,
  variable,
  variableMeta,
  vectorData,
  bathymetryData,
  bathymetryError,
  onHoverCoordinate,
  onSelectCoordinate,
  onClearSelection,
}) {
  return (
    <Canvas
      camera={{ position: [0, 5.4, 6.2], fov: 43, near: 0.1, far: 100 }}
      dpr={[1, 1.35]}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      frameloop="always"
      onPointerMissed={() => onClearSelection?.()}
    >
      <color attach="background" args={["#020810"]} />
      <OceanExtraction
        boundary={boundary}
        selectedCoordinate={selectedCoordinate}
        extractionState={extractionState}
        onHoverCoordinate={onHoverCoordinate}
        onSelectCoordinate={onSelectCoordinate}
        onClearSelection={onClearSelection}
      />
      {extractionState === "ocean" && bathymetryData && (
        <BathymetryMesh
          payload={bathymetryData}
          boundary={boundary}
          visible={variable === "bathymetry" || !liveData}
        />
      )}
      {extractionState === "ocean" && liveData && variable !== "bathymetry" && (
        <LiveOceanField
          payload={liveData}
          variable={variable}
          variableMeta={variableMeta}
          vectorPayload={vectorData?.u?.data?.levels?.[0] ? vectorData.u : liveData}
        />
      )}
    </Canvas>
  );
}
