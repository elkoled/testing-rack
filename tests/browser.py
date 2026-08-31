#!/usr/bin/env python3
"""Real-Chrome acceptance test for a running testing_rack deployment."""

from __future__ import annotations

import argparse
import os
import time
import uuid

from playwright.sync_api import sync_playwright


SCENARIOS = {
    "normal": "",
    "without-randomUUID": "delete Crypto.prototype.randomUUID",
    "without-webcrypto": "Object.defineProperty(globalThis,'crypto',{value:undefined,configurable:true})",
}
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 1000},
    "mobile": {"width": 390, "height": 844},
}


def run_case(browser, url: str, scenario: str, init_script: str, viewport: str) -> None:
    context = browser.new_context(viewport=VIEWPORTS[viewport])
    if init_script:
        context.add_init_script(init_script)
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(url, wait_until="networkidle")
        assert page.locator("#matrix .device").count() > 0
        assert page.locator("#count option").count() == 11
        assert page.locator("#rack-name").inner_text() == "chestnut_rack"
        assert page.locator("#agent-help").inner_text() == (
            "Clanker API: /api/agent"
        )
        name = f"chrome-{scenario[:8]}-{viewport[:1]}-{uuid.uuid4().hex[:6]}"
        page.locator("#name").fill(name)
        page.locator("#matrix .device", has_text="NUT001").click()
        assert page.locator("#matrix .selected").count() == 0
        assert page.locator("#count").input_value() == "0"
        assert page.locator("#reserve").is_disabled()
        page.locator("#matrix .device", has_text="NUT001").click()
        page.locator("#count").select_option("2")
        assert page.locator("#matrix .selected").count() == 2
        page.locator("#matrix .device", has_text="NUT002").click()
        page.locator("#matrix .device", has_text="NUT004").click()
        assert page.locator("#matrix .selected b").all_inner_texts() == ["NUT001", "NUT004"]
        started = time.monotonic()
        page.locator("#reserve").click()
        page.locator("#reservation").wait_for(state="visible")
        assert page.locator("#reservation-title").inner_text().startswith(f"{name} · ")
        command = page.locator("#command").inner_text()
        commands = command.splitlines()
        assert len(commands) == 2
        assert commands[0].startswith("ssh rack@chestnut -oSetEnv=R=")
        assert commands[0].endswith("-NUT001")
        assert commands[1].endswith("-NUT004")
        assert "min" not in page.locator("#reservation-title").inner_text()
        assert page.locator("#reserve-form").is_hidden()
        assert "loading" not in (
            page.locator("html").get_attribute("class") or ""
        ).split()
        assert page.locator("#controls").inner_text() == (
            "Append for actions: gpu_power:on · gpu_power:off · ftdi:reset"
        )
        assert page.locator("#copy-ssh").inner_text() == "Copy SSH"
        availability = page.locator("#availability").inner_text()
        assert "reserved ·" in availability and availability.endswith(" free")
        assert page.evaluate(
            """() => {
              dispatchEvent(new Event('beforeunload'))
              return getComputedStyle(document.body).visibility
            }"""
        ) == "hidden"
        page.locator("html").evaluate("element => element.classList.remove('loading')")
        # Persistence must not depend on retaining the URL fragment. A plain visit
        # and another tab in the same browser profile must restore the lease.
        page.goto(url, wait_until="networkidle")
        page.locator("#reservation").wait_for(state="visible")
        assert page.locator("#command").inner_text() == command
        second = context.new_page()
        second.goto(url, wait_until="networkidle")
        second.locator("#reservation").wait_for(state="visible")
        assert second.locator("#command").inner_text() == command
        second.close()
        # Existing reservations survive the one-time credential naming migration.
        page.evaluate(
            """() => {
              localStorage.setItem('testing-rack-capability', localStorage.getItem('testing-rack-token'))
              localStorage.removeItem('testing-rack-token')
            }"""
        )
        page.goto(url, wait_until="networkidle")
        page.locator("#reservation").wait_for(state="visible")
        assert page.locator("#command").inner_text() == command
        assert page.evaluate("localStorage.getItem('testing-rack-capability')") is None
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#release").click()
        page.locator("#reservation").wait_for(state="hidden")
        assert page.locator("#reserve-form").is_visible()
        assert "loading" not in (
            page.locator("html").get_attribute("class") or ""
        ).split()
        assert page.evaluate("localStorage.getItem('testing-rack-token')") is None
        # A stale local credential must self-heal rather than trapping the browser.
        page.evaluate("localStorage.setItem('testing-rack-token','111111111111')")
        page.reload(wait_until="networkidle")
        assert page.locator("#reserve-form").is_visible()
        assert page.evaluate("localStorage.getItem('testing-rack-token')") is None
        assert not errors, errors
        print(
            f"PASS chrome {scenario} {viewport} {int((time.monotonic() - started) * 1000)}ms"
        )
    finally:
        context.close()


def reserve(page, name: str) -> None:
    page.locator("#name").fill(name)
    page.locator("#count").select_option("1")
    page.locator("#reserve").click()


def release(page) -> None:
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#release").click()
    page.locator("#reservation").wait_for(state="hidden")


def run_interleavings(browser, url: str) -> None:
    # A rack can expose more ready devices than one reservation may claim.
    context = browser.new_context()
    page = context.new_page()
    page.goto(url, wait_until="networkidle")
    page.evaluate("ui.state.max_devices = 3\nrender()")
    assert page.locator("#count option").count() == 4
    for name in ("NUT002", "NUT003", "NUT004"):
        page.locator("#matrix .device", has_text=name).click()
    assert page.locator("#matrix .selected").count() == 3
    assert page.locator("#count").input_value() == "3"
    context.close()

    # Same profile, two tabs, simultaneous submit: exactly one lease and both tabs
    # must converge on it through the storage event.
    context = browser.new_context()
    a = context.new_page()
    b = context.new_page()
    a.goto(url, wait_until="networkidle")
    b.goto(url, wait_until="networkidle")
    name = "tabs-" + uuid.uuid4().hex[:8]
    for page in (a, b):
        page.locator("#name").fill(name)
        page.locator("#count").select_option("1")
    a.locator("#reserve").click(no_wait_after=True)
    b.locator("#reserve").click(no_wait_after=True)
    a.locator("#reservation").wait_for(state="visible", timeout=10000)
    b.locator("#reservation").wait_for(state="visible", timeout=10000)
    assert a.locator("#command").inner_text() == b.locator("#command").inner_text()
    release(a)
    b.locator("#reservation").wait_for(state="hidden", timeout=10000)
    context.close()

    # Separate profiles cannot create two leases with the same identity.
    first = browser.new_context()
    second = browser.new_context()
    p1 = first.new_page()
    p2 = second.new_page()
    p1.goto(url, wait_until="networkidle")
    p2.goto(url, wait_until="networkidle")
    name = "profiles-" + uuid.uuid4().hex[:8]
    reserve(p1, name)
    p1.locator("#reservation").wait_for(state="visible")
    p2.reload(wait_until="networkidle")
    assert p2.locator("#count option").count() == 10
    assert p2.locator("#count option").last.get_attribute("value") == "9"
    reserve(p2, name)
    p2.locator("#message").filter(has_text="already has reservation").wait_for(
        state="visible"
    )
    assert p2.locator("#reservation").is_hidden()
    release(p1)
    first.close()
    second.close()

    # Repeated rapid clicks cannot allocate more than one lease. Clipboard denial
    # must use the plain-HTTP fallback and leave the reservation usable.
    context = browser.new_context(permissions=[])
    page = context.new_page()
    page.goto(url, wait_until="networkidle")
    name = "repeat-" + uuid.uuid4().hex[:8]
    page.locator("#name").fill(name)
    page.evaluate(
        """() => {
          const form = document.querySelector('#reserve-form')
          for (const attempt of Array(8)) {
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
          }
        }"""
    )
    page.locator("#reservation").wait_for(state="visible")
    page.locator("#copy-ssh").click()
    page.locator("#copy-ssh").filter(has_text="Copied").wait_for(state="visible")
    assert page.locator("#reservation").is_visible()
    release(page)
    context.close()
    print("PASS chrome lifecycle interleavings")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8765")
    parser.add_argument("--chrome", default="/usr/bin/google-chrome")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        executable = args.chrome if os.path.exists(args.chrome) else None
        browser = playwright.chromium.launch(
            executable_path=executable, headless=True, args=["--no-sandbox"]
        )
        try:
            for scenario, script in SCENARIOS.items():
                for viewport in VIEWPORTS:
                    run_case(browser, args.url, scenario, script, viewport)
            run_interleavings(browser, args.url)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
