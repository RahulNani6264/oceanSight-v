function formatNumber(
  value,
  decimals = 3,
) {
  if (
    value === null ||
    value === undefined
  ) {
    return "—";
  }

  const number =
    Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return number.toFixed(
    decimals,
  );
}

function formatTime(
  value,
) {
  if (!value) {
    return "—";
  }

  const date =
    new Date(value);

  if (
    Number.isNaN(
      date.getTime(),
    )
  ) {
    return String(value);
  }

  return date.toLocaleString(
    undefined,
    {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone: "UTC",
      timeZoneName: "short",
    },
  );
}

function ValueRow({
  label,
  value,
  unit,
}) {
  return (
    <div className="scientific-value-row">
      <span className="scientific-value-label">
        {label}
      </span>

      <strong className="scientific-value-number">
        {value !== "—"
          ? `${value}${unit ? ` ${unit}` : ""}`
          : "—"}
      </strong>
    </div>
  );
}

function ScientificPointPanel({
  data,
  loading,
  error,
  coordinate,
  depthM,
  timeUtc,
  primaryVariable,
}) {
  if (!coordinate) {
    return null;
  }

  const waterColumn =
    data?.water_column;

  const waterData =
    waterColumn?.data;

  const bathymetry =
    data?.bathymetry;

  const physicalRelationship =
    data?.physical_relationship;

  const provenance =
    data?.provenance;

  const argoObservation =
    data?.argo_observation;

  const oceanAvailable =
    waterColumn?.available === true;

  const bathymetryAvailable =
    bathymetry?.available === true;

  const argoAvailable =
    argoObservation?.available ===
    true;

  const requestedDepth =
    physicalRelationship
      ?.requested_depth_m ??
    depthM;

  const actualDepth =
    waterData?.actual_depth_m ??
    null;

  const actualLatitude =
    waterData?.actual_latitude ??
    coordinate.lat;

  const actualLongitude =
    waterData?.actual_longitude ??
    coordinate.lon;

  const actualTime =
    waterData?.actual_time_utc ??
    null;

  const source =
    waterColumn?.source ??
    "—";

  const dataset =
    waterColumn?.dataset ??
    "—";

  // --------------------------------------------------------------------------
  // Scientific variable mapping
  // --------------------------------------------------------------------------

  const variableValues = {
    Temperature: {
      label: "Temperature",
      value:
        formatNumber(
          waterData?.temperature_c,
          3,
        ),
      unit: "°C",
    },

    Salinity: {
      label: "Salinity",
      value:
        formatNumber(
          waterData?.salinity_psu,
          3,
        ),
      unit: "PSU",
    },

    "Current Speed": {
      label: "Current Speed",
      value:
        formatNumber(
          waterData?.current_speed_m_s,
          4,
        ),
      unit: "m/s",
    },

    "Current Direction": {
      label: "Current Direction",
      value:
        formatNumber(
          waterData?.current_direction_math_deg,
          2,
        ),
      unit: "°",
    },

    "Wind Speed": {
      label: "Wind Speed",
      value: "—",
      unit: "",
    },

    "Wind Direction": {
      label: "Wind Direction",
      value: "—",
      unit: "",
    },

    SSH: {
      label: "Sea Surface Height",
      value:
        formatNumber(
          waterData?.ssh_m,
          4,
        ),
      unit: "m",
    },

    Pressure: {
      /*
       * The unified HYCOM point response does not currently
       * expose a scalar pressure field.
       *
       * Do not substitute Argo PRES here.
       */
      label: "Pressure",
      value: "—",
      unit: "",
    },

    Density: {
      label: "Density",
      value: "—",
      unit: "",
    },

    "Sound Speed": {
      label: "Sound Speed",
      value: "—",
      unit: "",
    },

    "Dissolved Oxygen": {
      label: "Dissolved Oxygen",
      value: "—",
      unit: "",
    },

    "Vertical Velocity": {
      label: "Vertical Velocity",
      value: "—",
      unit: "",
    },

    Vorticity: {
      label: "Vorticity",
      value: "—",
      unit: "",
    },

    "Wave Height": {
      label: "Wave Height",
      value: "—",
      unit: "",
    },

    "Wave Direction": {
      label: "Wave Direction",
      value: "—",
      unit: "",
    },

    "Wave Period": {
      label: "Wave Period",
      value: "—",
      unit: "",
    },

    "Air Pressure": {
      label: "Air Pressure",
      value: "—",
      unit: "",
    },

    "Chlorophyll-a": {
      label: "Chlorophyll-a",
      value: "—",
      unit: "",
    },

    Bathymetry: {
      label: "Seafloor Depth",
      value:
        formatNumber(
          bathymetry
            ?.depth_below_sea_level_m,
          2,
        ),
      unit: "m",
    },
  };

  const activeVariable =
    variableValues[
      primaryVariable
    ] ??
    variableValues.Temperature;

  return (
    <div className="scientific-point-panel">

      {/* ====================================================================
          HEADER
      ==================================================================== */}

      <div className="scientific-point-heading">

        <div>
          <div className="scientific-point-kicker">
            OCEAN STATE
          </div>

          <div className="scientific-point-title">
            {activeVariable.label}
          </div>
        </div>

        <div
          className={`scientific-data-badge ${
            oceanAvailable
              ? "scientific-data-badge-live"
              : ""
          }`}
        >
          {oceanAvailable
            ? "REAL DATA"
            : "UNAVAILABLE"}
        </div>

      </div>

      <div className="panel-divider" />

      {/* ====================================================================
          REQUEST CONTEXT
      ==================================================================== */}

      <div className="scientific-point-context">

        <div className="scientific-context-item">
          <span>
            REQUEST LAT
          </span>

          <strong>
            {formatNumber(
              coordinate.lat,
              4,
            )}
            °
          </strong>
        </div>

        <div className="scientific-context-item">
          <span>
            REQUEST LON
          </span>

          <strong>
            {formatNumber(
              coordinate.lon,
              4,
            )}
            °
          </strong>
        </div>

        <div className="scientific-context-item">
          <span>
            REQUEST DEPTH
          </span>

          <strong>
            {formatNumber(
              requestedDepth,
              1,
            )}{" "}
            m
          </strong>
        </div>

        <div className="scientific-context-item">
          <span>
            REQUEST TIME
          </span>

          <strong>
            {formatTime(
              timeUtc,
            )}
          </strong>
        </div>

      </div>

      {/* ====================================================================
          LOADING
      ==================================================================== */}

      {loading && (
        <div className="scientific-point-status">

          <span className="scientific-status-pulse" />

          Querying real scientific
          data…

        </div>
      )}

      {/* ====================================================================
          ERROR
      ==================================================================== */}

      {!loading &&
        error && (
          <div
            className="scientific-point-error"
            role="alert"
          >
            {error}
          </div>
        )}

      {/* ====================================================================
          REAL WATER COLUMN DATA
      ==================================================================== */}

      {!loading &&
        !error &&
        data && (
          <>
            <section className="scientific-data-section">

              <div className="scientific-section-title">
                SELECTED FIELD
              </div>

              <ValueRow
                label={
                  activeVariable.label
                }
                value={
                  activeVariable.value
                }
                unit={
                  activeVariable.unit
                }
              />

            </section>

            <section className="scientific-data-section">

              <div className="scientific-section-title">
                WATER COLUMN
              </div>

              <ValueRow
                label="Temperature"
                value={formatNumber(
                  waterData?.temperature_c,
                  3,
                )}
                unit="°C"
              />

              <ValueRow
                label="Salinity"
                value={formatNumber(
                  waterData?.salinity_psu,
                  3,
                )}
                unit="PSU"
              />

              <ValueRow
                label="U Current"
                value={formatNumber(
                  waterData?.u_current_m_s,
                  4,
                )}
                unit="m/s"
              />

              <ValueRow
                label="V Current"
                value={formatNumber(
                  waterData?.v_current_m_s,
                  4,
                )}
                unit="m/s"
              />

              <ValueRow
                label="Current Speed"
                value={formatNumber(
                  waterData?.current_speed_m_s,
                  4,
                )}
                unit="m/s"
              />

              <ValueRow
                label="Current Direction"
                value={formatNumber(
                  waterData?.current_direction_math_deg,
                  2,
                )}
                unit="°"
              />

              <ValueRow
                label="SSH"
                value={formatNumber(
                  waterData?.ssh_m,
                  4,
                )}
                unit="m"
              />

            </section>

            {/* ================================================================
                ACTUAL GRID MATCH
            ================================================================ */}

            <section className="scientific-data-section">

              <div className="scientific-section-title">
                ACTUAL SOURCE SAMPLE
              </div>

              <ValueRow
                label="Actual Latitude"
                value={formatNumber(
                  actualLatitude,
                  5,
                )}
                unit="°"
              />

              <ValueRow
                label="Actual Longitude"
                value={formatNumber(
                  actualLongitude,
                  5,
                )}
                unit="°"
              />

              <ValueRow
                label="Actual Depth"
                value={formatNumber(
                  actualDepth,
                  1,
                )}
                unit="m"
              />

              <div className="scientific-value-row scientific-value-row-time">
                <span className="scientific-value-label">
                  Actual Source Time
                </span>

                <strong className="scientific-value-number">
                  {formatTime(
                    actualTime,
                  )}
                </strong>
              </div>

            </section>

            {/* ================================================================
                BATHYMETRY
            ================================================================ */}

            <section className="scientific-data-section">

              <div className="scientific-section-title">
                GEBCO SEAFLOOR
              </div>

              <ValueRow
                label="Seafloor Depth"
                value={formatNumber(
                  bathymetry
                    ?.depth_below_sea_level_m,
                  2,
                )}
                unit="m"
              />

              <ValueRow
                label="Elevation"
                value={formatNumber(
                  bathymetry?.elevation_m,
                  2,
                )}
                unit="m"
              />

              <ValueRow
                label="Below Seafloor"
                value={
                  physicalRelationship
                    ?.below_seafloor ===
                  true
                    ? "YES"
                    : physicalRelationship
                        ?.below_seafloor ===
                      false
                    ? "NO"
                    : "—"
                }
                unit=""
              />

            </section>

            {/* ================================================================
                ARGO
            ================================================================ */}

            <section className="scientific-data-section">

              <div className="scientific-section-title">
                ARGO OBSERVATION
              </div>

              <ValueRow
                label="Availability"
                value={
                  argoAvailable
                    ? "AVAILABLE"
                    : "NO MATCH"
                }
                unit=""
              />

              {argoAvailable &&
                argoObservation
                  ?.profile && (
                  <>
                    <ValueRow
                      label="Platform"
                      value={
                        argoObservation
                          ?.profile
                          ?.platform_number ??
                        argoObservation
                          ?.profile
                          ?.platform ??
                        "—"
                      }
                      unit=""
                    />

                    <ValueRow
                      label="Cycle"
                      value={
                        argoObservation
                          ?.profile
                          ?.cycle_number ??
                        "—"
                      }
                      unit=""
                    />
                  </>
                )}

            </section>

            {/* ================================================================
                PROVENANCE
            ================================================================ */}

            <section className="scientific-data-section">

              <div className="scientific-section-title">
                PROVENANCE
              </div>

              <div className="scientific-provenance-row">
                <span>
                  OCEAN SOURCE
                </span>

                <strong>
                  {source}
                </strong>
              </div>

              <div className="scientific-provenance-row">
                <span>
                  DATASET
                </span>

                <strong>
                  {dataset}
                </strong>
              </div>

              <div className="scientific-provenance-row">
                <span>
                  SYNTHETIC DATA
                </span>

                <strong>
                  {provenance
                    ?.synthetic_data ===
                  false
                    ? "FALSE"
                    : "—"}
                </strong>
              </div>

              <div className="scientific-provenance-row">
                <span>
                  INTERPOLATION
                </span>

                <strong>
                  {provenance
                    ?.interpolation ===
                  false
                    ? "FALSE"
                    : "—"}
                </strong>
              </div>

            </section>
          </>
        )}

    </div>
  );
}

export default ScientificPointPanel;