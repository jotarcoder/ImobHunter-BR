from __future__ import annotations

import tempfile
import time
from pathlib import Path

from imobhunter.application.address_geocoding import CachedAddressGeocoder, GeocodingError
from imobhunter.domain.models import SearchRequest
from imobhunter.sources.geosampa import DEFAULT_LAYER, DEFAULT_WFS_URL, GeoSampaAdapter


# One query per municipality/region, deliberately sequential to respect
# Nominatim's public-service rate limit. These test geocoding, not cadastral
# coverage or legal ownership.
ADDRESSES = [
    ("Praia Grande/SP", "Avenida Presidente Costa e Silva, Praia Grande, São Paulo, Brasil"),
    ("São Paulo capital/SP", "Avenida Paulista, 1000, São Paulo, São Paulo, Brasil"),
    ("Rio de Janeiro/RJ", "Avenida Rio Branco, 1, Rio de Janeiro, Rio de Janeiro, Brasil"),
    ("Belo Horizonte/MG", "Praça Sete de Setembro, Belo Horizonte, Minas Gerais, Brasil"),
]


def main() -> None:
    user_agent = "ImobHunter-BR-live-smoke/0.1 (address coverage validation)"
    passed = 0
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="imobhunter-address-smoke-") as tmp:
        geocoder = CachedAddressGeocoder(
            Path(tmp) / "geocoding.sqlite3",
            user_agent=user_agent,
            minimum_interval=1.1,
        )
        for index, (label, query) in enumerate(ADDRESSES):
            if index:
                time.sleep(1.1)
            try:
                result = geocoder.geocode(query)
            except GeocodingError as exc:
                failures.append(f"{label}: GEOCODING FAILED — {exc}")
                print(f"FAIL {label}: {exc}")
                continue

            lat = result["latitude"]
            lon = result["longitude"]
            display_name = result["display_name"]
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                failures.append(f"{label}: coordinates outside valid ranges")
                print(f"FAIL {label}: invalid coordinates ({lat}, {lon})")
                continue
            passed += 1
            print(f"PASS {label}: lat={lat:.6f}, lon={lon:.6f}")
            print(f"  provider={result['provider']}; result={display_name}")

    print()
    print(f"GeoSampa endpoint: {DEFAULT_WFS_URL}")
    print(f"GeoSampa layer: {DEFAULT_LAYER}")
    adapter = GeoSampaAdapter(timeout=20)
    capital_request = SearchRequest(
        address="Avenida Paulista",
        number="1000",
        city="São Paulo",
        state="SP",
    )
    try:
        parcels = adapter.search(capital_request)
        print(f"São Paulo capital cadastral query: {len(parcels)} record(s)")
        for record in parcels[:3]:
            print(
                f"  address={record.address!r}; SQL={record.attributes.get('sql')!r}; "
                f"block={record.block!r}; lot={record.lot!r}; area_m2={record.area_m2!r}; "
                f"number_match={record.attributes.get('house_number_match')!r}; "
                f"geometry={'yes' if record.attributes.get('geometry_geojson') else 'no'}"
            )
        if not parcels:
            failures.append(
                "São Paulo capital: GeoSampa live cadastral query returned zero records "
                "for Avenida Paulista, 1000"
            )
    except Exception as exc:  # noqa: BLE001 - report real endpoint errors clearly.
        failures.append(f"São Paulo capital: GeoSampa request failed: {type(exc).__name__}: {exc}")
        print(f"FAIL São Paulo capital GeoSampa: {type(exc).__name__}: {exc}")

    print()
    print("Coverage boundary: the configured GeoSampa parcel layer is for São Paulo municipality.")
    print("Praia Grande/SP, RJ and MG results above confirm geocoding only; they do NOT confirm")
    print("parcel geometry, SQL/IPTU, land area, or ownership in those locations.")
    print(f"Geocoding result: {passed}/{len(ADDRESSES)} locations resolved.")
    if failures:
        print("SMOKE TEST FAILED:")
        for failure in failures:
            print(f" - {failure}")
        raise SystemExit(1)
    print("SMOKE TEST PASSED.")


if __name__ == "__main__":
    main()
