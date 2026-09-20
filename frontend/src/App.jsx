import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import MainGlobe from "./components/MainGlobe";
import OceanExtraction from "./components/OceanExtraction";
import LiveOceanField from "./components/LiveOceanField";
import { OceanSightApiError, getHycomTimes, getOceanBoundary, getOceanData, getOceanRegions, getOceanVariables, identifyOcean } from "./services/api";
import { normalizeOceanData, VECTOR_VARIABLES } from "./services/oceanData";

const FALLBACK_OCEANS = ["Pacific Ocean", "Atlantic Ocean", "Indian Ocean", "Southern Ocean", "Arctic Ocean"];
const FALLBACK_VARIABLES = [
  { id: "temperature", name: "Temperature", unit: "degree_Celsius", connected: true, render: { kind: "scalar", color_scale: ["#313695", "#74ADD1", "#FFFFBF", "#F46D43", "#A50026"] } },
  { id: "salinity", name: "Salinity", unit: "PSU", connected: true, render: { kind: "scalar", color_scale: ["#440154", "#31688E", "#35B779", "#FDE725"] } },
  { id: "current_u", name: "Eastward Current", unit: "m/s", connected: true, render: { kind: "vector_component", color_scale: ["#313695", "#74ADD1", "#FFFFBF", "#F46D43", "#A50026"] } },
  { id: "current_v", name: "Northward Current", unit: "m/s", connected: true, render: { kind: "vector_component", color_scale: ["#313695", "#74ADD1", "#FFFFBF", "#F46D43", "#A50026"] } },
  { id: "current_speed", name: "Current Speed", unit: "m/s", connected: true, render: { kind: "derived_scalar", color_scale: ["#0D0887", "#7201A8", "#D8576B", "#F0F921"] } },
  { id: "current_direction", name: "Current Direction", unit: "degree", connected: true, render: { kind: "derived_direction", color_scale: ["#440154", "#31688E", "#35B779", "#FDE725"] } },
  { id: "sea_surface_height", name: "Sea Surface Height", unit: "m", connected: true, render: { kind: "scalar", color_scale: ["#313695", "#74ADD1", "#FFFFBF", "#F46D43", "#A50026"] }, vertical: { supported: false, mode: "surface_only" } },
];
const normalizeLongitude = (value) => ((Number(value) + 540) % 360) - 180;
const formatCoord = (value, positive, negative) => Number.isFinite(Number(value)) ? `${Math.abs(Number(value)).toFixed(4)}°${Number(value) === 0 ? "" : Number(value) >= 0 ? ` ${positive}` : ` ${negative}`}` : "—";
const formatUtc = (value, withDate = false) => value && !Number.isNaN(new Date(value).getTime()) ? new Date(value).toLocaleString(undefined, { timeZone: "UTC", year: withDate ? "numeric" : undefined, month: withDate ? "short" : undefined, day: withDate ? "2-digit" : undefined, hour: "2-digit", minute: "2-digit", hour12: false }) : "—";
const timelineFor = (records) => records.filter((item) => typeof item?.time_utc === "string").map((item) => ({ timeUtc: item.time_utc })).sort((a, b) => new Date(a.timeUtc) - new Date(b.timeUtc));
const boundaryGeometry = (data) => data?.type === "Feature" ? data.geometry : data?.geometry ?? data?.boundary?.geometry ?? data?.boundary ?? null;

export default function App() {
  const [hoverCoordinate, setHoverCoordinate] = useState(null);
  const [selectedCoordinate, setSelectedCoordinate] = useState(null);
  const [flyToCoordinate, setFlyToCoordinate] = useState(null);
  const [oceans, setOceans] = useState(FALLBACK_OCEANS);
  const [selectedOcean, setSelectedOcean] = useState("");
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
  const [variables, setVariables] = useState(FALLBACK_VARIABLES);
  const [selectedVariable, setSelectedVariable] = useState("sea_surface_height");
  const [liveData, setLiveData] = useState(null);
  const [liveDataVariable, setLiveDataVariable] = useState(null);
  const [vectorData, setVectorData] = useState(null);
  const [liveDataLoading, setLiveDataLoading] = useState(false);
  const [liveDataError, setLiveDataError] = useState("");
  const [liveDataMeta, setLiveDataMeta] = useState(null);
  const [timeRecords, setTimeRecords] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [selectedTime, setSelectedTime] = useState("2026-09-14T06:00:00Z");
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarStart, setCalendarStart] = useState("");
  const [calendarEnd, setCalendarEnd] = useState("");
  const [activeRole, setActiveRole] = useState("Analyst");
  const earthActive = workspaceMode === "earth";
  const extractionActive = workspaceMode === "ocean";
  const coordinate = selectedCoordinate ?? hoverCoordinate;
  const selectedTimeIndex = useMemo(() => timeline.findIndex((item) => item.timeUtc === selectedTime), [timeline, selectedTime]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getOceanRegions(), getHycomTimes()]).then(([regions, times]) => {
      if (cancelled) return;
      const names = Array.isArray(regions?.oceans) ? regions.oceans.map((item) => item.name).filter(Boolean) : [];
      if (names.length) setOceans(names);
      const records = Array.isArray(times?.catalog?.times) ? times.catalog.times : [];
      const prepared = timelineFor(records);
      setTimeRecords(records); setTimeline(prepared);
      if (prepared.length) {
        const initial = prepared.find((item) => item.timeUtc === "2026-09-14T06:00:00Z") ?? prepared[0];
        setSelectedTime((current) => current || initial.timeUtc);
        const date = new Date(initial.timeUtc);
        setCalendarStart(date.toISOString().slice(0, 16)); setCalendarEnd(new Date(date.getTime() + 86400000).toISOString().slice(0, 16));
      }
    }).catch((requestError) => !cancelled && setError(requestError instanceof OceanSightApiError ? requestError.message : "Unable to load live dashboard metadata."));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;

    getOceanVariables().then((response) => {
      if (cancelled || !Array.isArray(response?.variables)) return;
      const connected = response.variables.filter((item) => item?.connected !== false && item?.id);
      if (connected.length) setVariables(connected);
    }).catch(() => {
      // The verified fallback catalog keeps the panel usable if metadata is unavailable.
    });

    return () => { cancelled = true; };
  }, []);

  const selectedVariableMeta = useMemo(
    () => variables.find((item) => item.id === selectedVariable) ?? FALLBACK_VARIABLES.find((item) => item.id === selectedVariable) ?? variables[0],
    [variables, selectedVariable],
  );

  useEffect(() => {
    if (!extractionActive || !selectedOcean || !selectedTime || !selectedVariableMeta?.connected) {
      setLiveDataLoading(false);
      setLiveDataError("");
      return undefined;
    }

    const controller = new AbortController();
    let cancelled = false;

    async function loadLiveField() {
      setLiveDataLoading(true);
      setLiveDataError("");

      try {
        const request = {
          mode: "ocean",
          ocean: selectedOcean,
          timeUtc: selectedTime,
          variable: selectedVariable,
          depthsM: "0",
          renderGridSize: 128,
          signal: controller.signal,
        };
        const primary = await getOceanData(request);
        let vectors = null;

        if (VECTOR_VARIABLES.has(selectedVariable)) {
          const [u, v] = await Promise.all([
            getOceanData({ ...request, variable: "current_u" }),
            getOceanData({ ...request, variable: "current_v" }),
          ]);
          vectors = { u, v };
        }

        const normalized = normalizeOceanData({
          payload: primary,
          variable: selectedVariable,
          vectorPayload: vectors,
        });

        if (cancelled) return;
        setLiveData(normalized.payload);
        setLiveDataVariable(selectedVariable);
        setVectorData(normalized.vectorPayload);
        setLiveDataMeta(normalized);
      } catch (requestError) {
        if (cancelled || requestError?.name === "AbortError") return;
        setLiveDataError(requestError instanceof OceanSightApiError || requestError instanceof Error ? requestError.message : "Live field request failed.");
        // Keep the last valid layer and metadata visible while reporting the new error.
      } finally {
        if (!cancelled) setLiveDataLoading(false);
      }
    }

    loadLiveField();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [extractionActive, selectedOcean, selectedTime, selectedVariable, selectedVariableMeta]);

  const clearSelection = () => { setSelectedCoordinate(null); setSearchMessage(""); };
  const selectCoordinate = (value) => { const lat = Number(value?.lat ?? value?.latitude); const lon = Number(value?.lon ?? value?.longitude); if (!Number.isFinite(lat) || !Number.isFinite(lon)) return; const next = { lat, lon: normalizeLongitude(lon) }; setSelectedCoordinate(next); setSearchLatitude(lat.toFixed(4)); setSearchLongitude(next.lon.toFixed(4)); };
  const handleHoverCoordinate = (value) => { if (!selectedCoordinate) { const lat = Number(value?.lat ?? value?.latitude); const lon = Number(value?.lon ?? value?.longitude); if (Number.isFinite(lat) && Number.isFinite(lon)) setHoverCoordinate({ lat, lon: normalizeLongitude(lon) }); } };

  async function searchCoordinate(event) {
    event.preventDefault(); setSearchLoading(true); setError(""); setSearchMessage("");
    try {
      const lat = Number(searchLatitude); const lon = Number(searchLongitude);
      if (!Number.isFinite(lat) || lat < -90 || lat > 90 || !Number.isFinite(lon) || lon < -180 || lon > 180) throw new Error("Enter a valid latitude (-90 to 90) and longitude (-180 to 180).");
      const next = { lat, lon: normalizeLongitude(lon) }; selectCoordinate(next); setFlyToCoordinate(next);
      const result = await identifyOcean({ latitude: lat, longitude: next.lon }); const ocean = result?.ocean?.name || "";
      if (ocean) { setSelectedOcean(ocean); setSearchOcean(ocean); }
      setSearchMessage(ocean ? `Point resolved to ${ocean}.` : "The selected coordinate could not be mapped to a supported ocean.");
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Coordinate search failed."); } finally { setSearchLoading(false); }
  }

  async function openOceanWorkspace(ocean = searchOcean || selectedOcean) {
    if (!ocean) return;
    setBoundaryLoading(true); setError(""); setSelectedOcean(ocean); setSearchOcean(ocean);
    try {
      const response = await getOceanBoundary({ ocean });
      if (!boundaryGeometry(response)?.coordinates) throw new Error(`The backend returned no usable boundary geometry for ${ocean}.`);
      setOceanBoundary(response); setWorkspaceMode("ocean"); setExtractionState("extracting"); setSearchMessage(`${ocean} boundary loaded from the scientific source. Extracting basin…`);
      window.setTimeout(() => { setExtractionState("ocean"); setSearchMessage(`${ocean} extracted. Real boundary geometry is now the active 3D workspace.`); }, 1600);
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "Ocean boundary extraction failed."); } finally { setBoundaryLoading(false); }
  }

  function applyCalendar(event) {
    event.preventDefault(); const start = new Date(calendarStart); const end = new Date(calendarEnd);
    if (Number.isNaN(start) || Number.isNaN(end) || end < start) { setError("Choose a valid start and end time."); return; }
    const records = timeRecords.filter((item) => item?.time_utc && new Date(item.time_utc) >= start && new Date(item.time_utc) <= end);
    if (!records.length) { setError("No exact scientific source timestamps are available in that calendar range."); return; }
    const next = timelineFor(records); setTimeline(next); setSelectedTime((current) => next.some((item) => item.timeUtc === current) ? current : next[0].timeUtc); setCalendarOpen(false); setError("");
  }

  return <div className={`ocean-app workspace-${workspaceMode} extraction-${extractionState}`}>
    <header className="top-nav"><div className="brand-lockup"><div className="brand-mark"><span /><span /></div><div><div className="brand-name">OCEANSIGHT</div><div className="brand-tag">OCEAN DIGITAL TWIN</div></div></div><nav className="main-nav" aria-label="Primary navigation"><button className="nav-link nav-link-active">Explore</button><button className="nav-link">Live Data</button><button className="nav-link">Research</button><button className="nav-link">Tools</button></nav><div className="top-actions"><div className="status-pill"><span className="status-dot" /> LIVE</div><select id="active-role" name="activeRole" value={activeRole} onChange={(event) => setActiveRole(event.target.value)} className="role-select"><option>Analyst</option><option>Fisheries</option><option>Disaster Management</option><option>Logistics</option><option>Navy</option></select><button className="icon-button" aria-label="Settings">⚙</button></div></header>
    <main className="dashboard-canvas">
      <aside className={`control-rail left-rail ${extractionActive && extractionState === "extracting" ? "rail-transition-out" : ""}`}><div className="rail-title-row"><div><div className="eyebrow">{earthActive ? "OCEAN DASHBOARD" : "OCEAN WORKSPACE"}</div><h1>{earthActive ? "Explore the oceans" : "Inspect the selected basin"}</h1></div><span className="rail-index">01</span></div><section className="rail-section location-section"><div className="section-title"><span>LOCATION</span><span>WHERE</span></div><div className="live-coordinate-card"><div className="coordinate-heading">{earthActive ? "CURSOR POSITION" : "SELECTED POINT"}</div><div className="coordinate-grid"><div><span>LAT</span><strong>{formatCoord(coordinate?.lat, "N", "S")}</strong></div><div><span>LON</span><strong>{formatCoord(coordinate?.lon, "E", "W")}</strong></div></div><div className={`coordinate-state ${selectedCoordinate ? "coordinate-state-selected" : ""}`}><span className="state-led" />{selectedCoordinate ? "POINT LOCKED" : earthActive ? "TRACKING CURSOR" : "NO POINT LOCKED"}</div></div><form className="search-card" onSubmit={searchCoordinate}><div className="mini-label">SEARCH COORDINATES</div><div className="two-up"><label htmlFor="search-latitude">Latitude<input id="search-latitude" name="searchLatitude" value={searchLatitude} onChange={(event) => setSearchLatitude(event.target.value)} placeholder="10.0000" /></label><label htmlFor="search-longitude">Longitude<input id="search-longitude" name="searchLongitude" value={searchLongitude} onChange={(event) => setSearchLongitude(event.target.value)} placeholder="80.0000" /></label></div><button className="primary-button" type="submit" disabled={searchLoading}>{searchLoading ? "RESOLVING…" : "RESOLVE OCEAN"}<span>↗</span></button></form></section><section className="rail-section"><div className="section-title"><span>OCEAN</span><span>WHAT</span></div><label className="select-field" htmlFor="ocean-selector"><span>SELECT OCEAN</span><select id="ocean-selector" name="searchOcean" value={searchOcean || selectedOcean} onChange={(event) => { setSearchOcean(event.target.value); setSelectedOcean(event.target.value); }}><option value="">Choose a basin</option>{oceans.map((ocean) => <option key={ocean} value={ocean}>{ocean}</option>)}</select></label><button className="secondary-button" type="button" onClick={() => openOceanWorkspace()} disabled={!searchOcean || boundaryLoading}>{boundaryLoading ? "LOADING REAL BOUNDARY…" : "EXTRACT OCEAN WORKSPACE"}<span>→</span></button>{selectedOcean && <div className="resolved-ocean"><span className="mini-ocean-dot" />{selectedOcean}<small>{earthActive ? "Boundary ready for extraction" : "Active scientific basin"}</small></div>}{extractionActive && <button type="button" className="back-to-earth-button" onClick={() => { setWorkspaceMode("earth"); setExtractionState("idle"); setSearchMessage(""); }}>← RETURN TO GLOBAL EARTH</button>}</section>{(searchMessage || error) && <div className={`feedback-box ${error ? "feedback-error" : ""}`}>{error || searchMessage}</div>}{selectedCoordinate && <button type="button" className="clear-button" onClick={clearSelection}>Clear point selection</button>}</aside>
      <section className="globe-stage"><div className="stage-head"><div><span className="stage-kicker">{earthActive ? "GLOBAL VIEW" : "OCEAN EXTRACTION"}</span><strong>{selectedOcean || "ALL OCEANS"}</strong></div><div className="stage-tools"><span className="source-chip">INCOIS · RECCAP2 · GEBCO</span><span className="view-chip">{earthActive ? "3D EARTH" : "REAL POLYGON"}</span></div></div><div className="globe-visual"><div className="glow-ring ring-one" /><div className="glow-ring ring-two" />{earthActive ? <MainGlobe onHoverCoordinate={handleHoverCoordinate} onSelectCoordinate={selectCoordinate} onClearSelection={clearSelection} selectedCoordinate={selectedCoordinate} flyToCoordinate={flyToCoordinate} transitionState="idle" /> : <div className="ocean-extraction-shell"><CanvasOceanWorkspace boundary={oceanBoundary} selectedCoordinate={selectedCoordinate} extractionState={extractionState} liveData={liveData} liveDataVariable={liveDataVariable} vectorData={vectorData} variableMeta={variables.find((item) => item.id === liveDataVariable)} onHoverCoordinate={handleHoverCoordinate} onSelectCoordinate={selectCoordinate} onClearSelection={clearSelection} /></div>}<div className="globe-caption">{earthActive ? <><span>MOVE CURSOR TO INSPECT</span><span>CLICK TO LOCK A COORDINATE</span></> : <><span>REAL SOURCE-MASK POLYGON</span><span>{extractionState === "extracting" ? "EXTRACTING BASIN…" : "BASIN READY FOR 3D SCIENCE"}</span></>}</div></div><div className="live-field-status"><span className={`live-field-dot ${liveDataLoading ? "is-loading" : liveData ? "is-live" : ""}`} /><span>{liveDataLoading ? `Loading ${selectedVariableMeta?.name || "field"}…` : liveDataError || (earthActive ? "Ocean-level globe view active" : `${selectedVariableMeta?.name || "Ocean field"} · server data`)}</span></div><div className="scene-bottom-callout"><div><span className="callout-dot" /><span>{earthActive ? "REAL SOURCE DATA" : "REAL OCEAN BOUNDARY"}</span></div><div>{selectedVariableMeta?.name || "OCEAN LEVEL"} · {activeRole.toUpperCase()}</div></div></section>
      <aside className="control-rail right-rail variable-rail"><div className="rail-title-row compact"><div><div className="eyebrow">LIVE FIELDS</div><h2>Variables</h2></div><span className="rail-index">02</span></div><section className="rail-section variable-section"><div className="section-title"><span>AVAILABLE VARIABLES</span><span>BACKEND</span></div><div className="variable-stack">{variables.map((variable) => { const active = variable.id === selectedVariable; return <button key={variable.id} type="button" className={`variable-row ${active ? "variable-row-active" : ""}`} onClick={() => setSelectedVariable(variable.id)} aria-pressed={active}><span className="variable-radio">{active ? "•" : ""}</span><span className="variable-name"><strong>{variable.name}</strong><small>{variable.unit || "—"}</small></span><span className="variable-status">{variable.connected === false ? "OFF" : active && liveDataLoading ? "LOAD" : active && liveDataError ? "ERROR" : active && liveDataMeta?.metadata?.isStale ? "STALE" : active && liveData ? "LIVE" : "READY"}</span></button>; })}</div></section><section className="rail-section scientific-state"><div className="section-title"><span>SELECTED FIELD</span><span>{selectedVariableMeta?.unit || "—"}</span></div><div className="metric-row"><span>FIELD</span><strong>{selectedVariableMeta?.name || selectedVariable}</strong></div><div className="metric-row"><span>UNIT</span><strong>{selectedVariableMeta?.unit || "—"}</strong></div><div className="metric-row"><span>LOAD</span><strong>{liveDataLoading ? "LOADING" : liveDataError ? "ERROR" : liveData && liveDataVariable === selectedVariable ? "LIVE" : liveData ? "CACHED LAYER" : "WAITING"}</strong></div>{liveDataMeta?.metadata?.isStale && <div className="stale-notice">SERVER MARKED THIS DATA STALE</div>}{liveDataError && <div className="feedback-box feedback-error">{liveDataError}</div>}</section><section className="rail-section field-legend"><div className="section-title"><span>COLOR LEGEND</span><span>{selectedVariableMeta?.unit || "—"}</span></div><div className="legend-gradient" style={{ background: `linear-gradient(90deg, ${(selectedVariableMeta?.render?.color_scale || ["#313695", "#74ADD1", "#FFFFBF", "#F46D43", "#A50026"]).join(", ")})` }} /><div className="legend-values"><span>{liveDataMeta?.range?.minimum ?? "—"}</span><span>{liveDataMeta?.range ? ((liveDataMeta.range.minimum + liveDataMeta.range.maximum) / 2).toPrecision(4) : "—"}</span><span>{liveDataMeta?.range?.maximum ?? "—"}</span></div></section><section className="rail-section scientific-state"><div className="section-title"><span>SERVER DATA</span><span>METADATA</span></div>{[["PROVIDER UPDATED", liveDataMeta?.metadata?.providerUpdatedAt], ["SERVER CACHED", liveDataMeta?.metadata?.serverCachedAt], ["NEXT REFRESH", liveDataMeta?.metadata?.nextRefreshAt], ["LAST ERROR", liveDataMeta?.metadata?.lastError]].map(([label, value]) => <div className="metric-row" key={label}><span>{label}</span><strong>{value || "—"}</strong></div>)}</section></aside>
    </main>
    <footer className="time-dock"><div className="time-summary"><span className="time-label">TIME NAVIGATION</span><strong>{formatUtc(selectedTime, true)}</strong><span className="time-mode">LIVE SOURCE</span></div><div className="timeline-core"><button className="time-step-button" type="button" disabled={selectedTimeIndex <= 0} onClick={() => setSelectedTime(timeline[selectedTimeIndex - 1]?.timeUtc)}>‹</button><div className="timeline-track">{timeline.length ? timeline.map((item) => <button key={item.timeUtc} type="button" className={`timeline-item ${item.timeUtc === selectedTime ? "timeline-item-active" : ""}`} onClick={() => setSelectedTime(item.timeUtc)}><span>{formatUtc(item.timeUtc)}</span></button>) : <div className="timeline-empty">Loading scientific source times…</div>}</div><button className="time-step-button" type="button" disabled={selectedTimeIndex < 0 || selectedTimeIndex >= timeline.length - 1} onClick={() => setSelectedTime(timeline[selectedTimeIndex + 1]?.timeUtc)}>›</button></div><div className="calendar-wrap"><button className={`calendar-button ${calendarOpen ? "calendar-button-active" : ""}`} type="button" onClick={() => setCalendarOpen((value) => !value)} aria-label="Open calendar range">▣</button>{calendarOpen && <form className="calendar-popover" onSubmit={applyCalendar}><div className="calendar-title">SCIENTIFIC RANGE</div><label htmlFor="calendar-start">START<input id="calendar-start" name="calendarStart" type="datetime-local" value={calendarStart} onChange={(event) => setCalendarStart(event.target.value)} /></label><label htmlFor="calendar-end">END<input id="calendar-end" name="calendarEnd" type="datetime-local" value={calendarEnd} onChange={(event) => setCalendarEnd(event.target.value)} /></label><button type="submit" className="primary-button">APPLY RANGE</button></form>}</div></footer>
  </div>;
}

function CanvasOceanWorkspace({ boundary, selectedCoordinate, extractionState, liveData, liveDataVariable, vectorData, variableMeta, onHoverCoordinate, onSelectCoordinate, onClearSelection }) {
  return <Canvas camera={{ position: [0, 5.4, 6.2], fov: 43, near: 0.1, far: 100 }} dpr={[1, 1.35]} gl={{ antialias: true, powerPreference: "high-performance" }} onPointerMissed={() => onClearSelection?.()}><color attach="background" args={["#020810"]} /><OceanExtraction boundary={boundary} selectedCoordinate={selectedCoordinate} extractionState={extractionState} onHoverCoordinate={onHoverCoordinate} onSelectCoordinate={onSelectCoordinate} onClearSelection={onClearSelection} />{liveData && <LiveOceanField payload={liveData} variable={liveDataVariable} variableMeta={variableMeta} vectorPayload={vectorData} />}</Canvas>;
}
