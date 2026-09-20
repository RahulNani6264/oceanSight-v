from app.ocean_variables import get_variable_catalog, get_variable_definition, normalize_variable_name


def test_hycom_aliases_normalize():
    assert normalize_variable_name("TEMP") == "temperature"
    assert normalize_variable_name("SALN") == "salinity"
    assert normalize_variable_name("UVEL") == "current_u"
    assert normalize_variable_name("VVEL") == "current_v"
    assert normalize_variable_name("SSH") == "sea_surface_height"


def test_current_speed_is_derived_from_real_components():
    item = get_variable_definition("current_speed")
    assert item["connected"] is True
    assert item["source"]["type"] == "derived"
    assert item["source"]["fields"] == ["UVEL", "VVEL"]


def test_external_variables_have_real_sources():
    wind = get_variable_definition("wind")
    pressure = get_variable_definition("air_pressure")
    chlorophyll = get_variable_definition("chlorophyll")

    assert wind["connected"] is True
    assert wind["source"]["provider"] == "NOAA NCEP"
    assert pressure["connected"] is True
    assert pressure["source"]["provider"] == "NOAA NCEP"
    assert chlorophyll["connected"] is True
    assert chlorophyll["source"]["provider"] == "NOAA NESDIS CoastWatch"


def test_catalog_contains_core_ocean_variables():
    ids = {item["id"] for item in get_variable_catalog()}
    assert {"temperature", "salinity", "current_u", "current_v", "current_speed", "bathymetry"}.issubset(ids)
