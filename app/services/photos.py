from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from app.config import Settings


BASE62_CHAR_SET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
DEFAULT_SHARED_ALBUM_HEADERS = {
    "Origin": "https://www.icloud.com",
    "Accept-Language": "en-US,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "text/plain",
    "Accept": "*/*",
    "Referer": "https://www.icloud.com/sharedalbum/",
    "Connection": "keep-alive",
}


class PhotoService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()

    def list_photos(self) -> list[dict[str, Any]]:
        if self._settings.photos_source == "icloud_shared_album":
            photos = self._from_icloud_shared_album()
            if photos:
                return photos[: self._settings.photos_limit]
            return self._from_directory()
        return self._from_directory()

    def _from_directory(self) -> list[dict[str, Any]]:
        root = self._settings.photos_directory
        if not root.exists():
            return []

        allowed_ext = {".jpg", ".jpeg", ".png", ".webp"}
        image_files = [
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in allowed_ext
        ]

        image_files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        photos: list[dict[str, Any]] = []
        for path in image_files[: self._settings.photos_limit]:
            relative = path.relative_to(root).as_posix()
            photos.append(
                {
                    "url": f"/media/{quote(relative, safe='/')}",
                    "caption": path.stem.replace("_", " ").strip(),
                    "source": "directory",
                }
            )
        return photos

    def _from_icloud_shared_album(self) -> list[dict[str, Any]]:
        if not self._settings.icloud_shared_album_url:
            return []

        token = _extract_album_token(self._settings.icloud_shared_album_url)
        if not token:
            return []

        base_url = _build_base_url(token)
        webstream_payload = self._post_shared_album(
            f"{base_url}/webstream",
            {"streamCtag": None},
            token=token,
            allow_relocation=True,
        )
        photos = webstream_payload.get("photos", [])
        if not photos:
            return []

        photo_guids = [photo.get("photoGuid") for photo in photos if photo.get("photoGuid")]
        asset_urls: dict[str, str] = {}
        for chunk in _chunk(photo_guids, 25):
            payload = self._post_shared_album(
                f"{base_url}/webasseturls",
                {"photoGuids": chunk},
                token=token,
                allow_relocation=True,
            )
            items = payload.get("items", {})
            for checksum, item in items.items():
                location = item.get("url_location")
                path = item.get("url_path")
                if location and path:
                    asset_urls[checksum] = f"https://{location}{path}"

        output: list[dict[str, Any]] = []
        for photo in photos:
            derivatives = photo.get("derivatives", {})
            checksum = _largest_derivative_checksum(derivatives)
            if not checksum:
                continue
            url = asset_urls.get(checksum)
            if not url:
                continue
            output.append(
                {
                    "url": url,
                    "caption": (photo.get("caption") or "").strip(),
                    "source": "icloud_shared_album",
                }
            )
        return output

    def _post_shared_album(
        self,
        url: str,
        payload: dict[str, Any],
        token: str,
        allow_relocation: bool,
    ) -> dict[str, Any]:
        response = self._session.post(
            url,
            headers=DEFAULT_SHARED_ALBUM_HEADERS,
            data=json.dumps(payload),
            timeout=self._settings.http_timeout_seconds,
            allow_redirects=False,
        )
        if response.status_code == 330 and allow_relocation:
            relocated_host = response.json().get("X-Apple-MMe-Host")
            if not relocated_host:
                raise RuntimeError("iCloud relocation response missing host")
            relocated_base = f"https://{relocated_host}/{token}/sharedstreams"
            relocated_url = relocated_base + url[url.rfind("/") :]
            relocated_response = self._session.post(
                relocated_url,
                headers=DEFAULT_SHARED_ALBUM_HEADERS,
                data=json.dumps(payload),
                timeout=self._settings.http_timeout_seconds,
                allow_redirects=False,
            )
            relocated_response.raise_for_status()
            return relocated_response.json()

        response.raise_for_status()
        return response.json()


def _chunk(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _base62_to_int(value: str) -> int:
    total = 0
    for char in value:
        total = total * 62 + BASE62_CHAR_SET.index(char)
    return total


def _build_base_url(token: str) -> str:
    shard_token = token.split(";")[0]
    if len(shard_token) < 2:
        raise ValueError("Invalid iCloud shared album token")
    if shard_token[0] == "A":
        server_partition = _base62_to_int(shard_token[1])
    else:
        if len(shard_token) < 3:
            raise ValueError("Invalid iCloud shared album token")
        server_partition = _base62_to_int(shard_token[1:3])
    return f"https://p{server_partition:02d}-sharedstreams.icloud.com/{token}/sharedstreams"


def _extract_album_token(shared_album_url: str) -> str | None:
    parsed = urlparse(shared_album_url)
    fragment = parsed.fragment
    if not fragment:
        return None
    return fragment.split("/")[-1].strip() or None


def _largest_derivative_checksum(derivatives: dict[str, Any]) -> str | None:
    best_checksum: str | None = None
    best_size = -1
    for derivative in derivatives.values():
        checksum = derivative.get("checksum")
        file_size = int(derivative.get("fileSize", 0))
        if checksum and file_size > best_size:
            best_size = file_size
            best_checksum = checksum
    return best_checksum
