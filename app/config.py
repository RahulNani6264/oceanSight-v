from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
RAW_DIR = BASE_DIR / "raw"
PROCESSED_DIR = BASE_DIR / "processed"
METADATA_DIR = BASE_DIR / "metadata"
LOG_DIR = BASE_DIR / "logs"


INCOIS_ERDDAP_BASE_URL = (
    "https://erddap.incois.gov.in/erddap"
)

INCOIS_TIMEOUT_SECONDS = 60


for directory in (
    DATA_DIR,
    RAW_DIR,
    PROCESSED_DIR,
    METADATA_DIR,
    LOG_DIR,
):
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )