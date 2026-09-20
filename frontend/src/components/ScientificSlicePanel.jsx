import React, { useMemo } from "react";

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined) {
    return "—";
  }

  const numeric = Number(value);

  if (!Number.isFinite(numeric)) {
    return "—";
  }

  return numeric.toFixed(digits);
}

function formatUtc(value) {
  if (!value) {
    return "—";
  }

  try {
    return new Date(value).toISOString();
  } catch {
    return String(value);
  }
}

function fieldUnit(variable) {
  switch (variable) {
    case "TEMP":
      return "°C";

    case "SALN":
      return "PSU";

    case "UVEL":
    case "VVEL":
      return "m/s";

    case "SSH":
      return "m";

    default:
      return "";
  }
}

function fieldLabel(variable) {
  switch (variable) {
    case "TEMP":
      return "Temperature";

    case "SALN":
      return "Salinity";

    case "UVEL":
      return "Eastward Current";

    case "VVEL":
      return "Northward Current";

    case "SSH":
      return "Sea Surface Height";

    default:
      return variable || "HYCOM Field";
  }
}

function cellDisplay(value) {
  if (value === null || value === undefined) {
    return "";
  }

  const numeric = Number(value);

  if (!Number.isFinite(numeric)) {
    return "";
  }

  return numeric.toFixed(2);
}

function valueToIntensity(value, minimum, maximum) {
  if (
    value === null ||
    value === undefined ||
    minimum === null ||
    maximum === null ||
    !Number.isFinite(Number(value))
  ) {
    return 0;
  }

  const numeric = Number(value);

  if (maximum <= minimum) {
    return 0.5;
  }

  return Math.max(
    0,
    Math.min(
      1,
      (numeric - minimum) / (maximum - minimum),
    ),
  );
}

function scientificCellBackground(
  value,
  minimum,
  maximum,
) {
  if (
    value === null ||
    value === undefined ||
    !Number.isFinite(Number(value))
  ) {
    return "rgba(255,255,255,0.035)";
  }

  const intensity = valueToIntensity(
    value,
    minimum,
    maximum,
  );

  /*
   * Scientific visualization intentionally uses
   * a neutral-to-blue gradient generated directly
   * from the normalized source value.
   *
   * No value is altered.
   */

  const red = Math.round(
    25 + intensity * 25,
  );

  const green = Math.round(
    75 + intensity * 105,
  );

  const blue = Math.round(
    120 + intensity * 120,
  );

  const alpha = 0.18 + intensity * 0.58;

  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function MetadataRow({ label, value }) {
  return (
    <div className="scientific-slice-meta-row">
      <span className="scientific-slice-meta-label">
        {label}
      </span>

      <span className="scientific-slice-meta-value">
        {value}
      </span>
    </div>
  );
}

export default function ScientificSlicePanel({
  data,
  loading = false,
  error = null,
}) {
  const grid = data?.grid;
  const requested = data?.requested;
  const actual = data?.actual;
  const variable = data?.variable;
  const statistics = data?.statistics;
  const source = data?.source;

  const latitudes = Array.isArray(
    grid?.latitudes,
  )
    ? grid.latitudes
    : [];

  const longitudes = Array.isArray(
    grid?.longitudes,
  )
    ? grid.longitudes
    : [];

  const values = Array.isArray(
    grid?.values,
  )
    ? grid.values
    : [];

  const missingMask = Array.isArray(
    grid?.missing_mask,
  )
    ? grid.missing_mask
    : [];

  const minimum =
    statistics?.minimum !== null &&
    statistics?.minimum !== undefined
      ? Number(statistics.minimum)
      : null;

  const maximum =
    statistics?.maximum !== null &&
    statistics?.maximum !== undefined
      ? Number(statistics.maximum)
      : null;

  const unit = fieldUnit(
    variable?.name,
  );

  const label = fieldLabel(
    variable?.name,
  );

  const safeRows = useMemo(() => {
    return values.map((row, rowIndex) => {
      if (!Array.isArray(row)) {
        return [];
      }

      return row.map(
        (cell, columnIndex) => {
          const isMissing =
            missingMask?.[rowIndex]?.[
              columnIndex
            ] === true;

          if (isMissing) {
            return null;
          }

          if (
            cell === null ||
            cell === undefined
          ) {
            return null;
          }

          const numeric = Number(cell);

          if (!Number.isFinite(numeric)) {
            return null;
          }

          return numeric;
        },
      );
    });
  }, [values, missingMask]);

  const sourceDatasets = Array.isArray(
    source?.datasets,
  )
    ? source.datasets
    : [];

  const sourceChunks = Array.isArray(
    source?.chunk_files,
  )
    ? source.chunk_files
    : [];

  const sourceUrls = Array.isArray(
    source?.source_urls,
  )
    ? source.source_urls
    : [];

  if (loading) {
    return (
      <div className="scientific-slice-panel scientific-slice-panel-loading">
        <div className="scientific-slice-status">
          Loading real INCOIS HYCOM field…
        </div>

        <div className="scientific-slice-spinner" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="scientific-slice-panel scientific-slice-panel-error">
        <div className="scientific-slice-section-title">
          HYCOM spatial field unavailable
        </div>

        <div className="scientific-slice-error-text">
          {error}
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="scientific-slice-panel">
        <div className="scientific-slice-section-title">
          Spatial scientific field
        </div>

        <div className="scientific-slice-muted">
          Select a real HYCOM-supported variable and
          exact source time to load the field.
        </div>
      </div>
    );
  }

  return (
    <div className="scientific-slice-panel">
      <div className="scientific-slice-header">
        <div>
          <div className="scientific-slice-eyebrow">
            REAL HYCOM FIELD
          </div>

          <div className="scientific-slice-title">
            {label}
          </div>
        </div>

        <div className="scientific-slice-unit">
          {unit}
        </div>
      </div>

      <div className="scientific-slice-section">
        <div className="scientific-slice-section-title">
          Scientific context
        </div>

        <MetadataRow
          label="Requested time"
          value={formatUtc(
            requested?.time_utc,
          )}
        />

        <MetadataRow
          label="Actual source time"
          value={formatUtc(
            actual?.time_utc,
          )}
        />

        <MetadataRow
          label="Requested depth"
          value={
            requested?.depth_m !== null &&
            requested?.depth_m !== undefined
              ? `${formatNumber(
                  requested.depth_m,
                  1,
                )} m`
              : "—"
          }
        />

        <MetadataRow
          label="Actual HYCOM depth"
          value={
            actual?.depth_m !== null &&
            actual?.depth_m !== undefined
              ? `${formatNumber(
                  actual.depth_m,
                  1,
                )} m`
              : "Surface field"
          }
        />

        <MetadataRow
          label="Selection"
          value={data.selection || "—"}
        />
      </div>

      <div className="scientific-slice-section">
        <div className="scientific-slice-section-title">
          Geographic bounds
        </div>

        <MetadataRow
          label="Latitude"
          value={`${formatNumber(
            requested?.latitude_min,
            4,
          )}° to ${formatNumber(
            requested?.latitude_max,
            4,
          )}°`}
        />

        <MetadataRow
          label="Longitude"
          value={`${formatNumber(
            requested?.longitude_min,
            4,
          )}° to ${formatNumber(
            requested?.longitude_max,
            4,
          )}°`}
        />

        <MetadataRow
          label="Grid"
          value={`${latitudes.length} × ${longitudes.length}`}
        />
      </div>

      <div className="scientific-slice-section">
        <div className="scientific-slice-section-title">
          Source statistics
        </div>

        <MetadataRow
          label="Minimum"
          value={
            minimum !== null
              ? `${formatNumber(
                  minimum,
                  4,
                )} ${unit}`
              : "—"
          }
        />

        <MetadataRow
          label="Maximum"
          value={
            maximum !== null
              ? `${formatNumber(
                  maximum,
                  4,
                )} ${unit}`
              : "—"
          }
        />

        <MetadataRow
          label="Valid cells"
          value={
            statistics?.valid_cells ??
            "—"
          }
        />

        <MetadataRow
          label="Missing cells"
          value={
            statistics?.missing_cells ??
            "—"
          }
        />
      </div>

      <div className="scientific-slice-field-wrapper">
        <div className="scientific-slice-section-title">
          Spatial field
        </div>

        <div className="scientific-slice-axis-caption">
          Longitude →
        </div>

        <div className="scientific-slice-grid">
          {safeRows.map(
            (row, rowIndex) => {
              const latitude =
                latitudes[rowIndex];

              return (
                <div
                  className="scientific-slice-row"
                  key={`slice-row-${latitude}-${rowIndex}`}
                >
                  <div className="scientific-slice-lat-label">
                    {formatNumber(
                      latitude,
                      3,
                    )}
                    °
                  </div>

                  <div className="scientific-slice-cells">
                    {row.map(
                      (
                        cell,
                        columnIndex,
                      ) => {
                        const longitude =
                          longitudes[
                            columnIndex
                          ];

                        const missing =
                          cell === null;

                        const cellStyle =
                          missing
                            ? {}
                            : {
                                background:
                                  scientificCellBackground(
                                    cell,
                                    minimum,
                                    maximum,
                                  ),
                              };

                        return (
                          <div
                            key={`slice-cell-${rowIndex}-${columnIndex}`}
                            className={
                              missing
                                ? "scientific-slice-cell scientific-slice-cell-missing"
                                : "scientific-slice-cell"
                            }
                            style={
                              cellStyle
                            }
                            title={
                              missing
                                ? `${formatNumber(
                                    latitude,
                                    4,
                                  )}°, ${formatNumber(
                                    longitude,
                                    4,
                                  )}° — missing source value`
                                : `${formatNumber(
                                    latitude,
                                    4,
                                  )}°, ${formatNumber(
                                    longitude,
                                    4,
                                  )}° — ${formatNumber(
                                    cell,
                                    4,
                                  )} ${unit}`
                            }
                          >
                            {cellDisplay(
                              cell,
                            )}
                          </div>
                        );
                      },
                    )}
                  </div>
                </div>
              );
            },
          )}
        </div>

        <div className="scientific-slice-longitude-axis">
          {longitudes.map(
            (
              longitude,
              index,
            ) => (
              <span
                key={`lon-label-${longitude}-${index}`}
              >
                {formatNumber(
                  longitude,
                  3,
                )}
                °
              </span>
            ),
          )}
        </div>

        <div className="scientific-slice-axis-caption scientific-slice-axis-caption-bottom">
          Latitude ↑
        </div>
      </div>

      <div className="scientific-slice-section">
        <div className="scientific-slice-section-title">
          Provenance
        </div>

        <MetadataRow
          label="Provider"
          value={
            source?.provider || "—"
          }
        />

        <MetadataRow
          label="Interpolation"
          value={
            data.interpolation === false
              ? "No"
              : "Yes"
          }
        />

        <MetadataRow
          label="Synthetic data"
          value={
            data.synthetic_data === false
              ? "No"
              : "Yes"
          }
        />

        {sourceDatasets.length >
          0 && (
          <div className="scientific-slice-source-list">
            <div className="scientific-slice-meta-label">
              Datasets
            </div>

            {sourceDatasets.map(
              (dataset) => (
                <div
                  key={dataset}
                  className="scientific-slice-source-item"
                >
                  {dataset}
                </div>
              ),
            )}
          </div>
        )}

        {sourceChunks.length >
          0 && (
          <div className="scientific-slice-source-list">
            <div className="scientific-slice-meta-label">
              Real chunk files
            </div>

            {sourceChunks.map(
              (chunk) => (
                <div
                  key={chunk}
                  className="scientific-slice-source-item"
                >
                  {chunk}
                </div>
              ),
            )}
          </div>
        )}

        {sourceUrls.length >
          0 && (
          <div className="scientific-slice-source-list">
            <div className="scientific-slice-meta-label">
              Source URLs
            </div>

            {sourceUrls.map(
              (url) => (
                <div
                  key={url}
                  className="scientific-slice-source-item"
                >
                  {url}
                </div>
              ),
            )}
          </div>
        )}
      </div>
    </div>
  );
}