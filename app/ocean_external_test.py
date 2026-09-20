from app.ocean_external import CONFIGS, OceanExternalDataEngine


def test_external_configs_use_real_noaa_sources():
    assert CONFIGS["wind"].dataset_id == "NCEP_Global_Best"
    assert CONFIGS["air_pressure"].field == "prmslmsl"
    assert CONFIGS["chlorophyll"].dataset_id == "noaacwNPPN20VIIRSDINEOFDaily"


def test_gfs_url_contains_real_forecast_fields():
    engine = OceanExternalDataEngine.__new__(OceanExternalDataEngine)
    url = engine._erddap_url(
        config=CONFIGS["wind"],
        time_utc="2026-09-14T00:00:00Z",
        latitude_min=-20,
        latitude_max=20,
        longitude_min=40,
        longitude_max=100,
        stride=2,
    )
    assert "NCEP_Global_Best.nc" in url
    assert "ugrd10m" in url and "vgrd10m" in url
    assert "2026-09-14T00:00:00Z" in url


def test_chlorophyll_url_uses_surface_product():
    engine = OceanExternalDataEngine.__new__(OceanExternalDataEngine)
    url = engine._erddap_url(
        config=CONFIGS["chlorophyll"],
        time_utc="2026-09-09T12:00:00Z",
        latitude_min=-10,
        latitude_max=10,
        longitude_min=60,
        longitude_max=80,
        stride=4,
    )
    assert "noaacwNPPN20VIIRSDINEOFDaily.nc" in url
    assert "chlor_a" in url
    assert "[(0)]" in url
