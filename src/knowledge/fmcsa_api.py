from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx


FMCSA_BASE = "https://mobile.fmcsa.dot.gov/qc/services"
FMCSA_WEB_KEY = os.getenv("FMCSA_WEB_KEY", "")

DATA_DIR = Path(__file__).parent.parent.parent / "data"


class FMCSAClient:
    """
    FMCSA SAFER Web Services client.
    Endpoint: https://mobile.fmcsa.dot.gov/qc/services/carriers/{dotNumber}
    Free API key at: https://ai.fmcsa.dot.gov/

    Falls back to mock data when FMCSA_WEB_KEY is not set — lets the
    system work in demo mode without requiring registration.
    """

    def __init__(self, web_key: str = FMCSA_WEB_KEY) -> None:
        self._key = web_key
        self._mock: dict[str, dict[str, Any]] = {}
        self._load_mock_data()
        self._timeout = httpx.Timeout(10.0)

    def _load_mock_data(self) -> None:
        path = DATA_DIR / "mock" / "carriers.json"
        if path.exists():
            for c in json.loads(path.read_text()):
                self._mock[c["dot_number"]] = c

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_carrier(self, dot_number: str) -> dict[str, Any]:
        """
        Fetch carrier data. Uses FMCSA API if FMCSA_WEB_KEY is set,
        otherwise falls back to mock data.
        """
        if self._key:
            try:
                return self._fetch_carrier_live(dot_number)
            except Exception as e:
                return {**self._get_mock(dot_number), "_source": "mock_fallback", "_error": str(e)}
        return {**self._get_mock(dot_number), "_source": "mock"}

    def get_carrier_basics(self, dot_number: str) -> dict[str, Any]:
        """
        Fetch carrier BASIC scores from FMCSA SMS.
        Returns normalized structure matching our internal CSAScore model.
        """
        if self._key:
            try:
                return self._fetch_basics_live(dot_number)
            except Exception as e:
                return {**self._get_mock_basics(dot_number), "_error": str(e)}
        return self._get_mock_basics(dot_number)

    def search_carriers_by_name(self, name: str) -> list[dict[str, Any]]:
        """Search carriers by legal name. Live API only."""
        if not self._key:
            results = [
                c for c in self._mock.values()
                if name.lower() in c.get("legal_name", "").lower()
            ]
            return [{"carrier": c, "_source": "mock"} for c in results]
        try:
            url = f"{FMCSA_BASE}/carriers/name/{name}?webKey={self._key}"
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
                return self._normalize_search_results(data)
        except Exception as e:
            return [{"error": str(e)}]

    # ── Live FMCSA API calls ───────────────────────────────────────────────────

    def _fetch_carrier_live(self, dot_number: str) -> dict[str, Any]:
        url = f"{FMCSA_BASE}/carriers/{dot_number}?webKey={self._key}"
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
        return self._normalize_carrier(data, dot_number)

    def _fetch_basics_live(self, dot_number: str) -> dict[str, Any]:
        # FMCSA SMS API for BASIC scores
        url = f"{FMCSA_BASE}/carriers/{dot_number}/basics?webKey={self._key}"
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
        return self._normalize_basics(data, dot_number)

    # ── Response normalisation (FMCSA → our model) ────────────────────────────

    def _normalize_carrier(self, data: dict[str, Any], dot_number: str) -> dict[str, Any]:
        """Map FMCSA API response fields to our Carrier model fields."""
        content = data.get("content", data)
        carrier = content.get("carrier", content)
        return {
            "dot_number": str(carrier.get("dotNumber", dot_number)),
            "mc_number": carrier.get("mcMxFFNumber"),
            "legal_name": carrier.get("legalName", "Unknown"),
            "dba_name": carrier.get("dbaName"),
            "operating_status": carrier.get("allowedToOperate", "N") == "Y" and "AUTHORIZED" or "NOT_AUTHORIZED",
            "carrier_operation": carrier.get("carrierOperation", {}).get("carrierOperationDesc", "CARRIER"),
            "hm_flag": carrier.get("hmFlag", "N") == "Y",
            "pc_flag": carrier.get("pcFlag", "N") == "Y",
            "state": carrier.get("phyState"),
            "country": carrier.get("phyCountry", "US"),
            "safety_rating": carrier.get("safetyRating"),
            "safety_rating_date": carrier.get("safetyRatingDate"),
            "insurance_on_file": carrier.get("bipdInsuranceRequired", "0") != "0",
            "insurance_amount": float(carrier.get("bipdInsuranceOnFile", 0) or 0),
            "out_of_service": carrier.get("oosDate") is not None,
            "out_of_service_date": carrier.get("oosDate"),
            "total_drivers": carrier.get("totalDrivers"),
            "total_power_units": carrier.get("totalPowerUnits"),
            "_source": "fmcsa_live",
        }

    def _normalize_basics(self, data: dict[str, Any], dot_number: str) -> dict[str, Any]:
        content = data.get("content", data)
        basics_list = content.get("basics", [])
        score_map: dict[str, float | None] = {}
        name_map = {
            "Unsafe Driving": "unsafe_driving",
            "Hours-Of-Service Compliance": "hours_of_service",
            "Driver Fitness": "driver_fitness",
            "Controlled Substances/Alcohol": "controlled_substances",
            "Vehicle Maintenance": "vehicle_maintenance",
            "Hazardous Materials Compliance": "hazmat_compliance",
            "Crash Indicator": "crash_indicator",
        }
        for b in basics_list:
            key = name_map.get(b.get("basicDesc", ""), "")
            if key:
                score_map[key] = b.get("percentile")
        return {"dot_number": dot_number, "csa_scores": score_map, "_source": "fmcsa_live"}

    def _normalize_search_results(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        content = data.get("content", {})
        carriers = content.get("carrier", [])
        if isinstance(carriers, dict):
            carriers = [carriers]
        return [{"carrier": self._normalize_carrier({"carrier": c}, c.get("dotNumber", "")), "_source": "fmcsa_live"} for c in carriers]

    # ── Mock fallback ──────────────────────────────────────────────────────────

    def _get_mock(self, dot_number: str) -> dict[str, Any]:
        return self._mock.get(dot_number, {
            "dot_number": dot_number,
            "legal_name": f"Carrier DOT {dot_number}",
            "operating_status": "UNKNOWN",
            "_note": "Not in local mock data. Set FMCSA_WEB_KEY for live lookup.",
        })

    def _get_mock_basics(self, dot_number: str) -> dict[str, Any]:
        carrier = self._mock.get(dot_number, {})
        return {
            "dot_number": dot_number,
            "csa_scores": carrier.get("csa_scores"),
            "_source": "mock",
        }

    # ── Convenience ────────────────────────────────────────────────────────────

    def is_live(self) -> bool:
        return bool(self._key)

    def status(self) -> dict[str, Any]:
        return {
            "mode": "live (FMCSA API)" if self.is_live() else "mock (set FMCSA_WEB_KEY for live)",
            "mock_carriers_loaded": len(self._mock),
            "fmcsa_base_url": FMCSA_BASE,
        }
