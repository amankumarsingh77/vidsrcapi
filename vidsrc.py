import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from typing import Optional, Tuple, Dict
from fastapi import FastAPI, Query

from sources.superembed import MultiembedExtractor
from sources.vidsrcpro import VidsrcStreamExtractor
from utils import Utilities

app = FastAPI()

SUPPORTED_SOURCES = ["VidSrc PRO", "Superembed"]

class VidsrcMeExtractor:
    BASE_URL: str = "https://vidsrc.me"
    RCP_URL: str = "https://rcp.vidsrc.me/rcp"

    def __init__(self, **kwargs) -> None:
        self.source_name = kwargs.get("source_name")
        self.fetch_subtitles = kwargs.get("fetch_subtitles")

    def get_sources(self, url: str) -> Tuple[Dict, str]:
        print(f"[>] Requesting {url}...")
        req = requests.get(url)

        if req.status_code != 200:
            print(f"[VidSrcExtractor] Couldn't fetch \"{req.url}\", status code: {req.status_code}\n[VidSrcExtractor] \"{self.BASE_URL}\" likely doesn't have the requested media...")
            print(req.url)
            return {}, f"https://{urlparse(req.url).hostname}/"

        soup = BeautifulSoup(req.text, "html.parser")
        return {source.text: source.get("data-hash") for source in soup.find_all("div", {"class", "server"}) if source.text and source.get("data-hash")}, f"https://{urlparse(req.url).hostname}/"

    def get_source(self, hash: str, referrer: str) -> Tuple[Optional[str], str]:
        url = f"{self.RCP_URL}/{hash}"
        print("[>] Requesting RCP domain...")

        req = requests.get(url, headers={"Referer": referrer})
        if req.status_code != 200:
            print(f"[VidSrcExtractor] Couldn't fetch \"{url}\", status code: {req.status_code}")
            return None, url

        soup = BeautifulSoup(req.text, "html.parser")
        encoded = soup.find("div", {"id": "hidden"}).get("data-h")
        seed = soup.find("body").get("data-i")

        source = Utilities.decode_src(encoded, seed)
        if source.startswith("//"):
            source = f"https:{source}"

        return source, url

    def get_source_url(self, url: str, referrer: str) -> Optional[str]:
        print("[>] Requesting source URL...")
        req = requests.get(url, allow_redirects=False, headers={"Referer": referrer})
        if req.status_code != 302:
            print(f"[VidSrcExtractor] Couldn't find redirect for \"{url}\", status code: {req.status_code}")
            return None

        return req.headers.get("location")

    def get_streams(self, media_id: str, season: Optional[str], episode: Optional[str]) -> Optional[Dict]:
        url = f"{self.BASE_URL}/embed/{media_id}"
        if season and episode:
            url += f"/{season}-{episode}/"

        sources, sources_referrer = self.get_sources(url)
        source = sources.get(self.source_name)
        if not source:
            available_sources = ", ".join(list(sources.keys()))
            print(f"[VidSrcExtractor] No source found for \"{self.source_name}\"\nAvailable Sources: {available_sources}")
            return None

        source_url, source_url_referrer = self.get_source(source, sources_referrer)
        if not source_url:
            print(f"[VidSrcExtractor] Could not retrieve source url, please check you can request \"{url}\", if this issue persists please open an issue.")
            return None
        
        final_source_url = self.get_source_url(source_url, source_url_referrer)
        if "vidsrc.stream" in final_source_url:
            print(f"[>] Fetching source for \"{self.source_name}\"...")

            extractor = VidsrcStreamExtractor()
            return extractor.resolve_source(url=source_url, referrer=source_url_referrer)
        
        elif "multiembed.mov" in final_source_url:
            extractor = MultiembedExtractor()
            return extractor.resolve_source(url=source_url, referrer=source_url_referrer)
        
        return None

@app.get("/get_streams")
async def get_streams(
    source_name: str = Query(..., title="Source Name", description="Name of the source"),
    media_id: str = Query(..., title="Media ID", description="IMDb or TMDB code of the media"),
    season: Optional[str] = Query(None, title="Season", description="Season number"),
    episode: Optional[str] = Query(None, title="Episode", description="Episode number")
):
    vse = VidsrcMeExtractor(
        source_name=source_name,
        fetch_subtitles=True
    )

    stream_data = vse.get_streams(
        media_id=media_id,
        season=season,
        episode=episode
    )

    if stream_data and  stream_data.get("streams"):
        return {"stream_url": stream_data["streams"][0]}
    else:
        return {"error": "Failed to retrieve stream URL"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
