"""Keep original reference pages and hashes for the traceability console design."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
from html.parser import HTMLParser


class Readable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())

ROOT = Path(__file__).resolve().parents[1] / "artifacts/frontend-research"
URLS = {
    "capra.html": "https://projects.eclipse.org/projects/modeling.capra",
    "capra-visualizations.html": "https://www.eclipse.org/community/eclipse_newsletter/2020/december/2.php",
    "cytoscape.html": "https://js.cytoscape.org/",
    "fastapi-upload.html": "https://fastapi.tiangolo.com/tutorial/request-files/",
}


def fetch(item):
    name, url = item
    try:
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=45) as response:
            data = response.read()
    except Exception as error:
        return {"url": url, "error": str(error)}
    (ROOT / name).write_bytes(data)
    parser = Readable()
    parser.feed(data.decode("utf-8", errors="replace"))
    (ROOT / name.replace(".html", ".txt")).write_text("\n".join(parser.parts), encoding="utf-8")
    return {"file": name, "url": url, "sha256": hashlib.sha256(data).hexdigest()}


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(fetch, URLS.items()))
    (ROOT / "manifest.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Saved {len(rows)} reference pages")
