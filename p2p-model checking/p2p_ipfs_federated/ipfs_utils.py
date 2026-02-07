"""
ipfs_utils.py – Upload / fetch model checkpoints via Pinata's IPFS pinning API.

Uses Pinata REST API (https://api.pinata.cloud) so no local IPFS daemon is needed.
Only requires the `requests` library.
"""

import io
import json
import os
import time
from pathlib import Path

import requests

from logs import setup_logging

logger = setup_logging("ipfs-utils")

# Pinata credentials (set via .env or environment)
PINATA_API_KEY = os.getenv("PINATA_API_KEY", "")
PINATA_API_SECRET = os.getenv("PINATA_API_SECRET", "")
PINATA_JWT = os.getenv("PINATA_JWT", "")

PINATA_API_URL = "https://api.pinata.cloud"
PINATA_GATEWAY_URL = os.getenv("PINATA_GATEWAY_URL", "https://gateway.pinata.cloud")


class IPFSClient:
    """Pinata-backed IPFS client.  All uploads go through Pinata's API,
    downloads go through the Pinata (or public) IPFS gateway."""

    def __init__(
        self,
        api_key: str = PINATA_API_KEY,
        api_secret: str = PINATA_API_SECRET,
        jwt: str = PINATA_JWT,
        gateway_url: str = PINATA_GATEWAY_URL,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.jwt = jwt
        self.gateway_url = gateway_url.rstrip("/")

    # ── Auth headers ─────────────────────────────────────────────────────

    def _headers(self) -> dict:
        """Return auth headers – prefer JWT, fall back to key/secret pair."""
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}"}
        return {
            "pinata_api_key": self.api_key,
            "pinata_secret_api_key": self.api_secret,
        }

    # ── Upload ───────────────────────────────────────────────────────────

    def upload_file(self, filepath: str, pin: bool = True) -> str:
        """
        Upload a file to IPFS via Pinata.  Returns the CID.

        Args:
            filepath: path to file on disk.
            pin:      always True for Pinata (files are pinned by default).
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        url = f"{PINATA_API_URL}/pinning/pinFileToIPFS"

        with open(filepath, "rb") as f:
            files = {"file": (filepath.name, f)}
            resp = requests.post(url, files=files, headers=self._headers(), timeout=120)

        resp.raise_for_status()
        cid = resp.json()["IpfsHash"]
        logger.info(f"Uploaded {filepath.name} → CID {cid}")
        return cid

    def upload_bytes(self, data: bytes, filename: str = "checkpoint.pt", pin: bool = True) -> str:
        """Upload raw bytes (e.g. serialised model weights) and return CID."""
        url = f"{PINATA_API_URL}/pinning/pinFileToIPFS"
        files = {"file": (filename, io.BytesIO(data))}
        resp = requests.post(url, files=files, headers=self._headers(), timeout=120)
        resp.raise_for_status()
        cid = resp.json()["IpfsHash"]
        logger.info(f"Uploaded bytes ({len(data)} B) → CID {cid}")
        return cid

    def upload_json(self, obj: dict, filename: str = "metadata.json", pin: bool = True) -> str:
        """Upload a JSON object via Pinata's pinJSONToIPFS endpoint."""
        url = f"{PINATA_API_URL}/pinning/pinJSONToIPFS"
        headers = {**self._headers(), "Content-Type": "application/json"}
        payload = {
            "pinataContent": obj,
            "pinataMetadata": {"name": filename},
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        cid = resp.json()["IpfsHash"]
        logger.info(f"Uploaded JSON → CID {cid}")
        return cid

    # ── Download ─────────────────────────────────────────────────────────

    def _gateway_get(self, url: str, **kwargs) -> requests.Response:
        """GET from the IPFS gateway with auth headers and retry logic.

        Sending the JWT/API-key headers with gateway requests avoids the
        aggressive 429 rate-limiting applied to unauthenticated public
        gateway traffic.  Includes exponential back-off as a safety net.
        """
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())          # add auth
        kwargs["headers"] = headers

        max_retries = kwargs.pop("max_retries", 4)
        last_resp: requests.Response | None = None

        for attempt in range(max_retries):
            resp = requests.get(url, **kwargs)
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning(
                    f"Rate-limited (429), retrying in {wait}s… "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                last_resp = resp
                continue
            resp.raise_for_status()
            return resp

        # All retries exhausted
        if last_resp is not None:
            last_resp.raise_for_status()
        raise requests.HTTPError("Download failed after retries")

    def download_to_file(self, cid: str, dest: str) -> str:
        """
        Fetch an object by CID from the IPFS gateway and write it to *dest*.
        Returns the absolute path written.
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)

        url = f"{self.gateway_url}/ipfs/{cid}"
        resp = self._gateway_get(url, timeout=120, stream=True)

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Downloaded CID {cid} → {dest}")
        return str(dest.resolve())

    def download_bytes(self, cid: str) -> bytes:
        """Fetch raw bytes by CID from the IPFS gateway."""
        url = f"{self.gateway_url}/ipfs/{cid}"
        resp = self._gateway_get(url, timeout=120)
        return resp.content

    def download_json(self, cid: str) -> dict:
        """Fetch a JSON object by CID."""
        raw = self.download_bytes(cid)
        return json.loads(raw)

    # ── Pin management ───────────────────────────────────────────────────

    def pin(self, cid: str) -> bool:
        """Pin an existing CID on Pinata (pinByHash)."""
        url = f"{PINATA_API_URL}/pinning/pinByHash"
        payload = {"hashToPin": cid}
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        logger.info(f"Pinned CID {cid}")
        return True

    def unpin(self, cid: str) -> bool:
        """Unpin a CID from Pinata."""
        url = f"{PINATA_API_URL}/pinning/unpin/{cid}"
        resp = requests.delete(url, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        logger.info(f"Unpinned CID {cid}")
        return True

    def is_pinned(self, cid: str) -> bool:
        """Check whether a CID is pinned on Pinata."""
        url = f"{PINATA_API_URL}/data/pinList"
        params = {"hashContains": cid, "status": "pinned"}
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            rows = resp.json().get("rows", [])
            return len(rows) > 0
        except Exception:
            return False

    # ── Utilities ────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if Pinata API is reachable and credentials are valid."""
        try:
            url = f"{PINATA_API_URL}/data/testAuthentication"
            resp = requests.get(url, headers=self._headers(), timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def get_gateway_url(self, cid: str) -> str:
        """Build a gateway URL for a given CID."""
        return f"{self.gateway_url}/ipfs/{cid}"
