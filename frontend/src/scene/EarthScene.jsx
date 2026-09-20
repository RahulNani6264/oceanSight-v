import {
  Suspense,
  useEffect,
  useMemo,
  useState,
} from "react";

import { Canvas } from "@react-three/fiber";

import Earth from "./Earth";

import {
  getHycomTimes,
  OceanSightApiError,
} from "../services/api";

// ============================================================================
// OCEANSIGHT 4D
// GLOBAL EARTH SCENE
// ============================================================================

const GLOBAL_VARIABLES = [
  {
    label: "Temperature",
    value: "Temperature",
    status: "available-source",
  },
  {
    label: "Salinity",
    value: "Salinity",
    status: "available-source",
  },
  {
    label: "Pressure",
    value: "Pressure",
    status: "not-connected",
  },
  {
    label: "Density",
    value: "Density",
    status: "not-connected",
  },
  {
    label: "Sound Speed",
    value: "Sound Speed",
    status: "not-connected",
  },
  {
    label: "Dissolved Oxygen",
    value: "Dissolved Oxygen",
    status: "not-connected",
  },
  {
    label: "Current Speed",
    value: "Current Speed",
    status: "not-connected",
  },
  {
    label: "Current Direction",
    value: "Current Direction",
    status: "not-connected",
  },
  {
    label: "Vertical Velocity",
    value: "Vertical Velocity",
    status: "not-connected",
  },
  {
    label: "Vorticity",
    value: "Vorticity",
    status: "not-connected",
  },
  {
    label: "SSH",
    value: "SSH",
    status: "available-source",
  },
  {
    label: "Wave Height",
    value: "Wave Height",
    status: "not-connected",
  },
  {
    label: "Wave Direction",
    value: "Wave Direction",
    status: "not-connected",
  },
  {
    label: "Wave Period",
    value: "Wave Period",
    status: "not-connected",
  },
  {
    label: "Wind Speed",
    value: "Wind Speed",
    status: "not-connected",
  },
  {
    label: "Wind Direction",
    value: "Wind Direction",
    status: "not-connected",
  },
  {
    label: "Air Pressure",
    value: "Air Pressure",
    status: "not-connected",
  },
  {
    label: "Chlorophyll-a",
    value: "Chlorophyll-a",
    status: "not-connected",
  },
  {
    label: "Bathymetry",
    value: "Bathymetry",
    status: "not-connected",
  },
];

// ============================================================================
// TIME HELPERS
// ============================================================================

function formatTimeLabel(timeUtc) {
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

function getTimeKind(timeUtc) {
  if (!timeUtc) {
    return "Unavailable";
  }

  const date = new Date(timeUtc);

  if (Number.isNaN(date.getTime())) {
    return "Unavailable";
  }

  const now = Date.now();

  if (date.getTime() < now) {
    return "Past";
  }

  if (date.getTime() > now) {
    return "Forecast";
  }

  return "Current";
}

// ============================================================================
// VARIABLE STATUS
// ============================================================================

function getGlobalVariableStatus(variable) {
  return (
    GLOBAL_VARIABLES.find(
      (item) => item.value === variable,
    ) ?? GLOBAL_VARIABLES[0]
  );
}

// ============================================================================
// TIME CONTROL
// ============================================================================

function TimeControl({
  hycomTimes = [],
  selectedTimeUtc = null,
  onTimeChange,
  timeLoading = false,
  timeError = "",
}) {
  const [open, setOpen] = useState(false);

  const safeTimes = Array.isArray(hycomTimes)
    ? hycomTimes.filter(
        (record) =>
          record &&
          typeof record.time_utc === "string",
      )
    : [];

  const selectedIndex = safeTimes.findIndex(
    (record) =>
      record.time_utc === selectedTimeUtc,
  );

  const currentIndex =
    selectedIndex >= 0
      ? selectedIndex
      : 0;

  const activeRecord =
    safeTimes[currentIndex] ?? null;

  const displayTime =
    selectedTimeUtc ??
    activeRecord?.time_utc ??
    null;

  const timeKind = getTimeKind(displayTime);

  const canGoPrevious = currentIndex > 0;

  const canGoNext =
    safeTimes.length > 0 &&
    currentIndex < safeTimes.length - 1;

  function moveTime(nextIndex) {
    if (
      nextIndex < 0 ||
      nextIndex >= safeTimes.length
    ) {
      return;
    }

    const record = safeTimes[nextIndex];

    if (!record?.time_utc) {
      return;
    }

    onTimeChange?.(record.time_utc);
  }

  return (
    <div
      className="time-control"
      onPointerDown={(event) => {
        event.stopPropagation();
      }}
      onClick={(event) => {
        event.stopPropagation();
      }}
    >
      <div className="time-control-header">
        <div>
          <div className="time-control-kicker">
            WHEN?
          </div>

          <div className="time-control-title">
            {timeLoading
              ? "Loading…"
              : formatTimeLabel(displayTime)}
          </div>
        </div>

        <button
          type="button"
          className={`time-toggle ${
            open ? "time-toggle-open" : ""
          }`}
          onClick={() =>
            setOpen((current) => !current)
          }
          aria-expanded={open}
          aria-label={
            open
              ? "Close time selector"
              : "Open time selector"
          }
        >
          {open ? "−" : "+"}
        </button>
      </div>

      <div className="time-control-meta">
        <span>{timeKind}</span>

        <span>
          {safeTimes.length} source
          {safeTimes.length === 1 ? "" : "s"}
        </span>
      </div>

      {open && (
        <div className="time-options">
          <div className="time-source-label">
            REAL HYCOM SOURCE TIMES
          </div>

          {timeError && (
            <div className="time-error">
              {timeError}
            </div>
          )}

          {!timeLoading &&
            !timeError &&
            safeTimes.length === 0 && (
              <div className="time-empty">
                No real HYCOM source timestamps available.
              </div>
            )}

          {safeTimes.length > 0 && (
            <>
              <div className="time-stepper">
                <button
                  type="button"
                  className="time-step-button"
                  disabled={!canGoPrevious}
                  onClick={() =>
                    moveTime(currentIndex - 1)
                  }
                  aria-label="Previous real HYCOM source time"
                >
                  ‹
                </button>

                <div className="time-step-value">
                  {currentIndex + 1}
                  {" / "}
                  {safeTimes.length}
                </div>

                <button
                  type="button"
                  className="time-step-button"
                  disabled={!canGoNext}
                  onClick={() =>
                    moveTime(currentIndex + 1)
                  }
                  aria-label="Next real HYCOM source time"
                >
                  ›
                </button>
              </div>

              <div
                className="time-source-list"
                role="listbox"
                aria-label="Available real HYCOM source times"
              >
                {safeTimes.map((record, index) => {
                  const active =
                    record.time_utc === selectedTimeUtc;

                  const kind = getTimeKind(
                    record.time_utc,
                  );

                  return (
                    <button
                      type="button"
                      key={`${record.time_utc}-${index}`}
                      className={`time-option ${
                        active
                          ? "time-option-active"
                          : ""
                      }`}
                      onClick={() => {
                        onTimeChange?.(
                          record.time_utc,
                        );

                        setOpen(false);
                      }}
                      aria-selected={active}
                    >
                      <span
                        className={`time-option-dot ${
                          active
                            ? "time-option-dot-active"
                            : ""
                        }`}
                      />

                      <span className="time-option-copy">
                        <span className="time-option-time">
                          {formatTimeLabel(
                            record.time_utc,
                          )}
                        </span>

                        <span className="time-option-kind">
                          {kind}
                        </span>
                      </span>

                      {active && (
                        <span className="time-option-check">
                          ✓
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// EARTH SCENE CONTENT
// ============================================================================

function EarthSceneContent({
  onHoverCoordinate,
  onSelectCoordinate,
  onClearSelection,

  selectedCoordinate,
  flyToCoordinate,

  transitionState = "idle",

  primaryVariable = "Temperature",
  hycomTimes = [],
  selectedTimeUtc = null,
  onTimeChange,

  timeLoading = false,
  timeError = "",
}) {
  const variableStatus =
    getGlobalVariableStatus(primaryVariable);

  const activeVariable = useMemo(
    () =>
      variableStatus?.value ??
      "Temperature",
    [variableStatus],
  );

  return (
    <div
      className={`earth-scene-container earth-transition-${transitionState}`}
      data-transition-state={transitionState}
      data-active-variable={activeVariable}
    >
      <Canvas
        camera={{
          position: [0, 0, 7.1],
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
        onPointerMissed={() => {
          onClearSelection?.();
        }}
      >
        <Suspense fallback={null}>
          <Earth
            onHoverCoordinate={onHoverCoordinate}
            onSelectCoordinate={onSelectCoordinate}
            selectedCoordinate={selectedCoordinate}
            flyToCoordinate={flyToCoordinate}
            transitionState={transitionState}
          />
        </Suspense>
      </Canvas>

      <TimeControl
        hycomTimes={hycomTimes}
        selectedTimeUtc={selectedTimeUtc}
        onTimeChange={onTimeChange}
        timeLoading={timeLoading}
        timeError={timeError}
      />
    </div>
  );
}

// ============================================================================
// MAIN EARTH SCENE
// ============================================================================

export default function EarthScene({
  onHoverCoordinate,
  onSelectCoordinate,
  onClearSelection,

  selectedCoordinate,
  flyToCoordinate,

  transitionState = "idle",

  primaryVariable = "Temperature",

  hycomTimes: externalHycomTimes = null,
  selectedTimeUtc: externalSelectedTimeUtc = null,
  onTimeChange: externalOnTimeChange,

  timeLoading: externalTimeLoading = false,
  timeError: externalTimeError = "",
}) {
  const [
    internalHycomTimes,
    setInternalHycomTimes,
  ] = useState([]);

  const [
    internalSelectedTimeUtc,
    setInternalSelectedTimeUtc,
  ] = useState(null);

  const [
    internalTimeLoading,
    setInternalTimeLoading,
  ] = useState(
    externalHycomTimes === null,
  );

  const [
    internalTimeError,
    setInternalTimeError,
  ] = useState("");

  const usingExternalTimes =
    Array.isArray(externalHycomTimes);

  const hycomTimes =
    usingExternalTimes
      ? externalHycomTimes
      : internalHycomTimes;

  const selectedTimeUtc =
    usingExternalTimes
      ? externalSelectedTimeUtc
      : internalSelectedTimeUtc;

  const timeLoading =
    usingExternalTimes
      ? externalTimeLoading
      : internalTimeLoading;

  const timeError =
    usingExternalTimes
      ? externalTimeError
      : internalTimeError;

  useEffect(() => {
    if (usingExternalTimes) {
      return undefined;
    }

    let cancelled = false;

    async function loadTimes() {
      setInternalTimeLoading(true);
      setInternalTimeError("");

      try {
        const payload = await getHycomTimes();

        if (cancelled) {
          return;
        }

        let records = [];

        if (Array.isArray(payload?.times)) {
          records = payload.times;
        } else if (Array.isArray(payload?.catalog)) {
          records = payload.catalog;
        } else if (
          Array.isArray(payload?.catalog?.times)
        ) {
          records = payload.catalog.times;
        }

        records = records
          .filter(
            (record) =>
              record &&
              typeof record.time_utc === "string",
          )
          .sort(
            (a, b) =>
              new Date(a.time_utc).getTime() -
              new Date(b.time_utc).getTime(),
          );

        setInternalHycomTimes(records);

        if (records.length > 0) {
          setInternalSelectedTimeUtc(
            (current) => {
              const currentExists =
                Boolean(current) &&
                records.some(
                  (record) =>
                    record.time_utc === current,
                );

              return currentExists
                ? current
                : records[0].time_utc;
            },
          );
        } else {
          setInternalSelectedTimeUtc(null);

          setInternalTimeError(
            "No real HYCOM source timestamps are available.",
          );
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        setInternalHycomTimes([]);
        setInternalSelectedTimeUtc(null);

        setInternalTimeError(
          error instanceof OceanSightApiError
            ? error.message
            : error instanceof Error
              ? error.message
              : "Unable to load real HYCOM source times.",
        );
      } finally {
        if (!cancelled) {
          setInternalTimeLoading(false);
        }
      }
    }

    loadTimes();

    return () => {
      cancelled = true;
    };
  }, [usingExternalTimes]);

  function handleTimeChange(timeUtc) {
    if (usingExternalTimes) {
      externalOnTimeChange?.(timeUtc);
      return;
    }

    const exists = internalHycomTimes.some(
      (record) =>
        record?.time_utc === timeUtc,
    );

    if (!exists) {
      return;
    }

    setInternalSelectedTimeUtc(timeUtc);
  }

  return (
    <EarthSceneContent
      onHoverCoordinate={onHoverCoordinate}
      onSelectCoordinate={onSelectCoordinate}
      onClearSelection={onClearSelection}
      selectedCoordinate={selectedCoordinate}
      flyToCoordinate={flyToCoordinate}
      transitionState={transitionState}
      primaryVariable={primaryVariable}
      hycomTimes={hycomTimes}
      selectedTimeUtc={selectedTimeUtc}
      onTimeChange={handleTimeChange}
      timeLoading={timeLoading}
      timeError={timeError}
    />
  );
}