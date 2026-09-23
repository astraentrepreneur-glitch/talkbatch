"""Optional isolated browser smoke check; requires existing Playwright/Chromium."""

import argparse
import json
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright, expect

from make_demo import make_demo
from talkbatch import validate_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshot", type=Path, help="Optional screenshot of synthetic app data only.")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        source, plan = make_demo(Path(folder) / "fixture")
        browser = playwright.chromium.launch(
            channel="chromium", headless=True, chromium_sandbox=True, ignore_default_args=True,
            args=["--headless=new", "--remote-debugging-pipe",
                  "--no-first-run", "--no-default-browser-check"])
        try:
            context = browser.new_context(accept_downloads=True, viewport={"width": 1120, "height": 900})
            context.route("http://**/*", lambda route: route.abort())
            context.route("https://**/*", lambda route: route.abort())
            page = context.new_page()
            errors = []
            network = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: network.append(request.url)
                    if request.url.startswith(("http://", "https://")) else None)
            page.goto(Path(__file__).with_name("index.html").resolve().as_uri())
            for label, url in (
                ("Follow the synthetic walkthrough", "https://astraentrepreneur-glitch.github.io/talkbatch/walkthrough.html"),
                ("get the free planner/exporter package", "https://github.com/astraentrepreneur-glitch/talkbatch/releases/tag/v0.1.0-preview"),
            ):
                link = page.get_by_role("link", name=label, exact=True)
                expect(link).to_be_visible()
                expect(link).to_have_attribute("href", url)
                expect(link).to_have_attribute("rel", "noopener noreferrer")
            expect(page.get_by_role("button", name="Download validated plan")).to_be_disabled()
            assert page.evaluate("TalkBatch.parseTime('01:02:03.5')") == 3723.5
            assert page.evaluate("TalkBatch.parseTime('1e-7')") == 1e-7
            assert page.evaluate("TalkBatch.filename(0, '../../Caf\u00e9 / Intro')") == "001-cafe-intro.webm"
            for bad in ("1:60", "-1", "NaN", "1::2", ""):
                assert page.evaluate("""value => {
                    try { TalkBatch.parseTime(value); return false; }
                    catch (_) { return true; }
                }""", bad)
            page.locator("#source-file").set_input_files(source)
            expect(page.locator("#source-status")).to_contain_text("Browser-local preview.")
            page.locator("#plan-file").set_input_files(source.parent / "demo-plan.json")
            expect(page.locator(".group")).to_have_count(3)
            expect(page.get_by_role("button", name="Download validated plan")).to_be_enabled()
            def seek(seconds):
                return page.locator("video").evaluate("""(video, seconds) => new Promise((resolve, reject) => {
                    const timer = setTimeout(() => reject(new Error("Synthetic preview seek timed out")), 10000);
                    video.addEventListener("seeked", () => {
                        clearTimeout(timer);
                        resolve({time: video.currentTime, ready: video.readyState});
                    }, {once: true});
                    video.currentTime = seconds;
                })""", seconds)
            assert seek(4.7)["ready"] >= 2
            page.locator(".group").first.get_by_role("button", name="In = playhead", exact=True).click()
            expect(page.get_by_role("button", name="Download validated plan")).to_be_disabled()
            assert seek(5.7)["ready"] >= 2
            page.locator(".group").first.get_by_role("button", name="Out = playhead", exact=True).click()
            expect(page.locator(".group").first.get_by_label("Range 1 start", exact=True)).to_have_value("4.700")
            expect(page.locator(".group").first.get_by_label("Range 1 end", exact=True)).to_have_value("5.700")
            page.locator(".group").first.get_by_label("Range 1 start", exact=True).fill("1")
            page.locator(".group").first.get_by_label("Range 1 end", exact=True).fill("2")
            with page.expect_download() as event:
                page.get_by_role("button", name="Download validated plan").click()
            downloaded = Path(folder) / "downloaded.json"
            event.value.save_as(downloaded)
            actual = validate_plan(json.loads(downloaded.read_text()))
            assert actual["groups"] == plan["groups"]
            assert actual["source"]["name"] == source.name
            first = page.locator(".group").first
            first.get_by_label("Range 1 end", exact=True).fill("0")
            expect(page.get_by_role("button", name="Download validated plan")).to_be_disabled()
            first.get_by_label("Range 1 end", exact=True).fill("2")
            expect(page.get_by_role("button", name="Download validated plan")).to_be_enabled()
            first.get_by_role("button", name="Move down", exact=True).click()
            expect(page.locator(".filename").first).to_have_text("001-two-ranges.webm")
            page.locator(".group").first.get_by_role("button", name="Move down", exact=True).click()
            expect(page.locator(".filename").first).to_have_text("001-single-range.webm")
            first = page.locator(".group").first
            first.get_by_label("Output 1 title", exact=True).fill("<img src=x onerror=alert(1)>")
            assert page.locator("img").count() == 0
            first.get_by_label("Output 1 title", exact=True).fill("Single range")
            if args.screenshot:
                page.screenshot(path=str(args.screenshot), full_page=True)
            assert not errors, errors
            assert not network, network
            context.close()
        finally:
            browser.close()
    print("Browser smoke passed: preview/seek/marks/import/download, validation, reorder, plain-text titles; no page HTTP requests.")


if __name__ == "__main__":
    main()
