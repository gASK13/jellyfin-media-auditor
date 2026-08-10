from __future__ import annotations
from typing import Any
import requests

class JellyfinClient:
    def __init__(self, url: str, api_key: str, user_id: str | None = None): self.url=url.rstrip("/"); self.user_id=user_id; self.session=requests.Session(); self.session.headers["X-Emby-Token"] = api_key
    def _request(self, method: str, path: str, *, params: Any = None, json: Any = None) -> requests.Response:
        response = self.session.request(method, f"{self.url}{path}", params=params, json=json, timeout=30)
        response.raise_for_status()
        return response
    def _get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params).json()
    def get_item(self, item_id: str) -> dict[str, Any]:
        if not self.user_id: raise RuntimeError("jellyfin.user_id is required for item-detail requests on this server")
        return self._get(f"/Users/{self.user_id}/Items/{item_id}")
    def movies(self, library_id: str) -> list[dict[str, Any]]:
        return self._get("/Items", ParentId=library_id, IncludeItemTypes="Movie", Recursive="true", Fields="Path,MediaSources,ProviderIds,DateCreated,PremiereDate").get("Items", [])
    def refresh_item(self, item_id: str) -> None:
        self._request("POST", f"/Items/{item_id}/Refresh", params={"MetadataRefreshMode":"None","ImageRefreshMode":"None","ReplaceAllMetadata":"false","ReplaceAllImages":"false"})
    def item_tags(self, item_id: str) -> list[str]: return list(self.get_item(item_id).get("Tags") or [])
    def update_tags(self, item_id: str, tags: Any) -> None:
        item = self.get_item(item_id)
        item["Tags"] = sorted(list(tags))
        self._request("POST", f"/Items/{item_id}", json=item)
    def add_tags(self, item_id: str, tags: set[str]) -> None:
        if tags: self.update_tags(item_id, set(self.item_tags(item_id)) | tags)
    def remove_tags(self, item_id: str, tags: set[str]) -> None:
        if tags: self.update_tags(item_id, set(self.item_tags(item_id)) - tags)
