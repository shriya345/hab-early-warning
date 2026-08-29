
import pandas as pd


SATELLITE_FILE = "data/sentinel2/sentinel_index.csv"
ENVIRONMENT_FILE = "data/environmental/processed/environmental_dataset.csv"

EXPECTED_SATELLITE_COLUMNS = [
    "date",
    "image_path",
    "cloud_percentage"
]

EXPECTED_ENVIRONMENT_COLUMNS = [
    "date",
    "lat",
    "lon",
    "chlorophyll_a",
    "sst",
    "rainfall",
    "wind_speed"
]


def load_and_validate_inputs(
    satellite_file=SATELLITE_FILE,
    environment_file=ENVIRONMENT_FILE
):
    """
    Load satellite and environmental datasets and verify
    that both follow the agreed team schema.
    """

    satellite = pd.read_csv(
        satellite_file,
        parse_dates=["date"]
    )

    environment = pd.read_csv(
        environment_file,
        parse_dates=["date"]
    )

    if list(satellite.columns) != EXPECTED_SATELLITE_COLUMNS:
        raise ValueError(
            "Satellite file has incorrect columns.\n"
            f"Expected: {EXPECTED_SATELLITE_COLUMNS}\n"
            f"Received: {list(satellite.columns)}"
        )

    if list(environment.columns) != EXPECTED_ENVIRONMENT_COLUMNS:
        raise ValueError(
            "Environmental file has incorrect columns.\n"
            f"Expected: {EXPECTED_ENVIRONMENT_COLUMNS}\n"
            f"Received: {list(environment.columns)}"
        )

    satellite = satellite.sort_values("date").reset_index(drop=True)
    environment = environment.sort_values("date").reset_index(drop=True)

    print("✓ Satellite dataset validated.")
    print("✓ Environmental dataset validated.")

    print("\nSatellite samples:", len(satellite))
    print("Environmental samples:", len(environment))

    print(
        "Satellite date range:",
        satellite["date"].min(),
        "to",
        satellite["date"].max()
    )

    print(
        "Environmental date range:",
        environment["date"].min(),
        "to",
        environment["date"].max()
    )

    return satellite, environment


if __name__ == "__main__":
    load_and_validate_inputs()
