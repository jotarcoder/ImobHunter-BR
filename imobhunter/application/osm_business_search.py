from __future__ import annotations

from typing import Any

import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "ImobHunter-BR/0.1 (desktop market intelligence)"


def fetch_osm_businesses(
    latitude: float,
    longitude: float,
    radius_km: float,
    *,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch named business/amenity features from OpenStreetMap for a small radius."""
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Coordenadas inválidas.")
    if not (0 < radius_km <= 25):
        raise ValueError("A busca online aceita raio entre 0 e 25 km.")
    radius_m = int(radius_km * 1000)
    query = f"""
    [out:json][timeout:30];
    (
      nwr(around:{radius_m},{latitude},{longitude})["name"]["shop"];
      nwr(around:{radius_m},{latitude},{longitude})["name"]["office"];
      nwr(around:{radius_m},{latitude},{longitude})["name"]["craft"];
      nwr(around:{radius_m},{latitude},{longitude})["name"]["industrial"];
      nwr(around:{radius_m},{latitude},{longitude})["name"]["amenity"~"restaurant|cafe|bank|pharmacy|clinic|hospital|fuel|marketplace|car_repair|dentist|fast_food|bar|school|university|coworking"];
    );
    out center tags;
    """
    owned = client is None
    http = client or httpx.Client(
        timeout=httpx.Timeout(40.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )
    try:
        response = http.post(OVERPASS_URL, data={"data": query})
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Não foi possível consultar o OpenStreetMap agora. Tente novamente mais tarde.") from exc
    finally:
        if owned:
            http.close()
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise RuntimeError("A fonte de mapas retornou uma resposta inválida.")
    places: list[dict[str, Any]] = []
    for element in payload["elements"]:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        name = str(tags.get("name") or "").strip()
        if not name:
            continue
        center = element.get("center") or {}
        lat = element.get("lat", center.get("lat"))
        lon = element.get("lon", center.get("lon"))
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        business_type = (tags.get("shop") or tags.get("office") or tags.get("craft") or tags.get("industrial") or tags.get("amenity") or "empresa")
        street = tags.get("addr:street", "")
        number = tags.get("addr:housenumber", "")
        address = " ".join(part for part in (street, number) if part)
        places.append({
            "name": name,
            "cnae": str(business_type),
            "address": address,
            "city": str(tags.get("addr:city") or ""),
            "state": str(tags.get("addr:state") or ""),
            "latitude": lat,
            "longitude": lon,
            "source": f"OpenStreetMap ({element.get('type')}:{element.get('id')})",
        })
    return places
