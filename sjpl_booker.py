#!/usr/bin/env python3
"""
SJPL Branch Study Room Auto-Booker
===================================
Automates booking of Village Square Branch study rooms at booking.sjlibrary.org

Requirements:
    pip install selenium webdriver-manager

Usage:
    python sjpl_booker.py                    # Interactive mode
    python sjpl_booker.py --auto             # Auto-book next available 2hr slot
    python sjpl_booker.py --date 2026-02-09  # Book for a specific date
    python sjpl_booker.py --time 10:00       # Prefer a specific start time
    python sjpl_booker.py --cron             # Cron mode: book max days ahead, both accounts
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
)

# ─── Configuration ───────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "sjpl_config.json"

# Default configuration
DEFAULT_CONFIG = {
    "accounts": [
        {
            "name": "Account 1",
            "library_card": "21197912155248",
            "pin": "",  # <-- SET YOUR PIN HERE or in sjpl_config.json
        },
        {
            "name": "Account 2",
            "library_card": "21197911113594",
            "pin": "",  # <-- SET YOUR PIN HERE or in sjpl_config.json
        },
    ],
    "target_rooms": [
        {
            "name": "Group Study Room 1 - Village Square",
            "space_id": 131580,
            "url": "https://booking.sjlibrary.org/space/131580",
        },
        {
            "name": "Group Study Room 2 - Village Square",
            "space_id": 131582,
            "url": "https://booking.sjlibrary.org/space/131582",
        },
    ],
    "preferences": {
        "preferred_times": ["10:00", "12:00", "14:00", "16:00"],
        "booking_duration_hours": 2,  # Max 2 hours per day
        "max_days_ahead": 4,
        "headless": False,  # Set True for background operation
        "slow_mode": False,  # Add delays for debugging
        "screenshot_on_error": True,
    },
    "base_url": "https://booking.sjlibrary.org",
    "branch_rooms_url": "https://booking.sjlibrary.org/reserve/spaces/branch-study-rooms",
}


# ─── Logging Setup ───────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("sjpl_booker.log"),
    ],
)
log = logging.getLogger("sjpl_booker")


# ─── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class Account:
    name: str
    library_card: str
    pin: str


@dataclass
class Room:
    name: str
    space_id: int
    url: str


@dataclass
class BookingResult:
    success: bool
    account: str
    room: str
    date: str
    time_slot: str
    message: str = ""


# ─── Config Manager ─────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load config from file or create default."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config = json.load(f)
        log.info(f"Loaded config from {CONFIG_FILE}")
        return config
    else:
        save_config(DEFAULT_CONFIG)
        log.info(f"Created default config at {CONFIG_FILE}")
        return DEFAULT_CONFIG


def save_config(config: dict):
    """Save config to file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


# ─── Browser Setup ───────────────────────────────────────────────────────────

def create_driver(headless: bool = False) -> webdriver.Chrome:
    """Create and configure Chrome WebDriver."""
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # Suppress automation flags
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    try:
        # Try using webdriver-manager for auto driver management
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except ImportError:
        # Fall back to system chromedriver
        driver = webdriver.Chrome(options=options)

    driver.implicitly_wait(5)
    return driver


# ─── Core Booking Engine ─────────────────────────────────────────────────────

class SJPLBooker:
    """Main booking automation class."""

    AVAILABILITY_URL = "https://booking.sjlibrary.org/space/{space_id}"
    RESERVE_URL = "https://booking.sjlibrary.org/reserve/spaces/branch-study-rooms"

    def __init__(self, config: dict):
        self.config = config
        self.accounts = [Account(**a) for a in config["accounts"]]
        self.rooms = [Room(**r) for r in config["target_rooms"]]
        self.prefs = config["preferences"]
        self.driver: Optional[webdriver.Chrome] = None
        self.wait: Optional[WebDriverWait] = None
        self.results: list[BookingResult] = []

    def start(self):
        """Initialize the browser."""
        log.info("Starting browser...")
        self.driver = create_driver(headless=self.prefs.get("headless", False))
        self.wait = WebDriverWait(self.driver, 15)
        log.info("Browser started successfully")

    def stop(self):
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            log.info("Browser closed")

    def _slow(self, seconds: float = 1.0):
        """Optional delay for debugging."""
        if self.prefs.get("slow_mode"):
            time.sleep(seconds)

    def _screenshot(self, name: str = "error"):
        """Take a screenshot for debugging."""
        if self.prefs.get("screenshot_on_error"):
            filename = f"screenshot_{name}_{datetime.now().strftime('%H%M%S')}.png"
            self.driver.save_screenshot(filename)
            log.info(f"Screenshot saved: {filename}")

    # ── Navigation ────────────────────────────────────────────────────────

    def navigate_to_room(self, room: Room, target_date: str):
        """
        Navigate to a room's availability page for a specific date.
        target_date format: YYYY-MM-DD
        """
        url = f"{self.AVAILABILITY_URL.format(space_id=room.space_id)}"
        log.info(f"Navigating to {room.name}: {url}")
        self.driver.get(url)
        self._slow()
        time.sleep(3)  # Let the page and calendar load

        # Navigate to the correct date if needed
        self._navigate_to_date(target_date)

    def _navigate_to_date(self, target_date: str):
        """Navigate the availability calendar to the target date."""
        target = datetime.strptime(target_date, "%Y-%m-%d").date()
        today = datetime.now().date()
        days_ahead = (target - today).days

        if days_ahead < 0:
            log.error("Cannot book in the past!")
            return
        if days_ahead > 4:
            log.warning("SJPL only allows booking up to 4 days ahead")
            return

        log.info(f"Navigating to date: {target_date} ({days_ahead} days ahead)")

        # The LibCal availability grid typically shows dates as clickable headers
        # or has a date picker. Try multiple approaches:

        # Approach 1: Look for a date picker input
        try:
            date_input = self.driver.find_element(By.CSS_SELECTOR, "input[type='date'], input.fc-datepicker, #s-lc-date")
            date_input.clear()
            date_input.send_keys(target_date)
            self._slow()
            return
        except NoSuchElementException:
            pass

        # Approach 2: Click the date on the availability grid header
        try:
            # LibCal typically shows dates at the top of the availability grid
            date_formatted = target.strftime("%-m/%-d/%Y")  # e.g., "2/9/2026"
            date_links = self.driver.find_elements(By.XPATH, f"//a[contains(text(), '{target.strftime('%b %-d')}')]")
            if date_links:
                date_links[0].click()
                self._slow()
                return
        except Exception:
            pass

        # Approach 3: Use the "next day" navigation buttons
        try:
            for _ in range(days_ahead):
                next_btn = self.driver.find_element(
                    By.CSS_SELECTOR, ".fc-next-button, .s-lc-eq-next, [aria-label='Next'], .next-day"
                )
                next_btn.click()
                time.sleep(1)
        except NoSuchElementException:
            log.warning("Could not find date navigation; the page may already show the right date")

    # ── Slot Selection ────────────────────────────────────────────────────

    def find_available_slots(self, preferred_time: str = None) -> list:
        """
        Find available time slots on the current availability grid.
        Returns list of clickable slot elements.
        """
        time.sleep(2)  # Ensure grid is loaded

        available_slots = []

        # LibCal uses various CSS classes for available slots
        selectors = [
            "a.s-lc-eq-avail",            # Standard available slot
            "td.s-lc-eq-avail",           # Table cell available
            ".s-lc-eq-checkout a",         # Checkout-style
            "[class*='avail']:not([class*='unavail'])",  # Generic available
            ".fc-event",                   # FullCalendar events
            "a[data-seq]",                # Slots with sequence data
            ".grid-slot.available",        # Grid-based available slots
        ]

        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    available_slots.extend(elements)
                    log.info(f"Found {len(elements)} available slots with selector: {selector}")
                    break
            except Exception:
                continue

        if not available_slots:
            log.warning("No available slots found with CSS selectors, trying XPath...")
            try:
                # Look for any clickable time elements
                available_slots = self.driver.find_elements(
                    By.XPATH,
                    "//td[contains(@class,'avail') or contains(@class,'open')]"
                    "//a | //div[contains(@class,'slot') and contains(@class,'available')]"
                )
            except Exception:
                pass

        log.info(f"Total available slots found: {len(available_slots)}")
        return available_slots

    def select_time_slots(self, preferred_time: str = None, duration_hours: int = 2):
        """
        Select time slots for the desired duration.
        LibCal typically uses a grid where you click start time,
        then select end time from a dropdown.
        """
        log.info(f"Selecting {duration_hours}hr slot (preferred: {preferred_time or 'any'})")

        # Wait for the availability grid to load
        time.sleep(3)

        # Strategy 1: Click on available time slots in the grid
        available = self.find_available_slots()

        if not available:
            log.error("No available time slots found!")
            self._screenshot("no_slots")
            return False

        # Try to find the slot closest to preferred time
        target_slot = None
        if preferred_time:
            for slot in available:
                try:
                    slot_text = slot.text or slot.get_attribute("title") or slot.get_attribute("data-start") or ""
                    if preferred_time in slot_text:
                        target_slot = slot
                        log.info(f"Found preferred time slot: {slot_text}")
                        break
                except StaleElementReferenceException:
                    continue

        # Fall back to first available slot
        if not target_slot and available:
            target_slot = available[0]
            slot_text = target_slot.text or target_slot.get_attribute("title") or "unknown"
            log.info(f"Using first available slot: {slot_text}")

        if target_slot:
            try:
                # Scroll into view and click
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_slot)
                time.sleep(0.5)
                target_slot.click()
                log.info("Clicked start time slot")
                self._slow()
                time.sleep(2)

                # After clicking start time, LibCal typically shows an end-time dropdown
                self._select_end_time(duration_hours)
                return True

            except ElementClickInterceptedException:
                log.warning("Click intercepted, trying JavaScript click...")
                self.driver.execute_script("arguments[0].click();", target_slot)
                time.sleep(2)
                self._select_end_time(duration_hours)
                return True
        
        return False

    def _select_end_time(self, duration_hours: int):
        """Select the end time in the booking duration dropdown."""
        try:
            # Look for end-time dropdown (common in LibCal)
            end_time_selectors = [
                "select#end-time",
                "select[name='end']",
                "select.s-lc-eq-endtime",
                "#s-lc-eq-enddt",
                "select[id*='end']",
                "select[id*='duration']",
            ]

            for selector in end_time_selectors:
                try:
                    dropdown = self.driver.find_element(By.CSS_SELECTOR, selector)
                    from selenium.webdriver.support.ui import Select
                    select = Select(dropdown)

                    # Try to select the max duration (2 hours)
                    options = select.options
                    log.info(f"End-time options: {[o.text for o in options]}")

                    # Select the last option (usually max duration) or the 2hr option
                    for opt in reversed(options):
                        opt_text = opt.text.lower()
                        if "2" in opt_text and ("hour" in opt_text or "hr" in opt_text or ":00" in opt_text):
                            select.select_by_visible_text(opt.text)
                            log.info(f"Selected end time: {opt.text}")
                            return
                    
                    # Just pick the last (longest) option
                    select.select_by_index(len(options) - 1)
                    log.info(f"Selected end time (last option): {options[-1].text}")
                    return

                except NoSuchElementException:
                    continue

            # If no dropdown, maybe we need to click more slots for duration
            log.info("No end-time dropdown found; may need to click additional time slots")

        except Exception as e:
            log.warning(f"Could not select end time: {e}")

    # ── Submit Booking ────────────────────────────────────────────────────

    def submit_times(self) -> bool:
        """Click the 'Submit Times' / 'Continue' button."""
        submit_selectors = [
            "#s-lc-eq-bsubmit",
            "button[type='submit']",
            "input[type='submit']",
            "button.btn-primary",
            "#btn-form-submit",
            "a.s-lc-eq-checkout",
        ]
        submit_xpaths = [
            "//button[contains(text(), 'Submit')]",
            "//input[@value='Submit']",
            "//button[contains(text(), 'Continue')]",
            "//button[contains(text(), 'Book')]",
            "//a[contains(text(), 'Submit')]",
            "//a[contains(text(), 'Continue')]",
        ]

        # Try CSS selectors first
        for selector in submit_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed():
                    btn.click()
                    log.info(f"Clicked submit button: {selector}")
                    time.sleep(3)
                    return True
            except (NoSuchElementException, ElementClickInterceptedException):
                continue

        # Try XPath
        for xpath in submit_xpaths:
            try:
                btn = self.driver.find_element(By.XPATH, xpath)
                if btn.is_displayed():
                    btn.click()
                    log.info(f"Clicked submit button: {xpath}")
                    time.sleep(3)
                    return True
            except (NoSuchElementException, ElementClickInterceptedException):
                continue

        log.error("Could not find submit button!")
        self._screenshot("no_submit")
        return False

    # ── Authentication ────────────────────────────────────────────────────

    def authenticate(self, account: Account) -> bool:
        """
        Log in with library card number and PIN.
        SJPL uses LibAuth which typically shows a login form.
        """
        log.info(f"Authenticating as {account.name} ({account.library_card})")

        time.sleep(3)  # Wait for the auth page to load

        # Check if we're on a login page
        page_source = self.driver.page_source.lower()

        if "library card" in page_source or "barcode" in page_source or "login" in page_source:
            log.info("Login form detected")

            # Library card number field
            card_selectors = [
                "#library-card",
                "#barcode",
                "#username",
                "input[name='barcode']",
                "input[name='username']",
                "input[name='library_card']",
                "input[name='cardnumber']",
                "input[placeholder*='card']",
                "input[placeholder*='barcode']",
                "#s-lc-auth-barcode",
                "input[id*='card']",
                "input[id*='barcode']",
            ]

            card_input = None
            for selector in card_selectors:
                try:
                    card_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if card_input.is_displayed():
                        break
                    card_input = None
                except NoSuchElementException:
                    continue

            if not card_input:
                # Try by label text
                try:
                    labels = self.driver.find_elements(By.TAG_NAME, "label")
                    for label in labels:
                        if any(kw in label.text.lower() for kw in ["card", "barcode", "username"]):
                            for_attr = label.get_attribute("for")
                            if for_attr:
                                card_input = self.driver.find_element(By.ID, for_attr)
                                break
                except Exception:
                    pass

            if not card_input:
                # Last resort: find any visible text input
                inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])")
                for inp in inputs:
                    if inp.is_displayed():
                        card_input = inp
                        break

            if card_input:
                card_input.clear()
                card_input.send_keys(account.library_card)
                log.info("Entered library card number")
            else:
                log.error("Could not find library card input!")
                self._screenshot("no_card_input")
                return False

            # PIN field
            pin_selectors = [
                "#pin",
                "#password",
                "input[name='pin']",
                "input[name='password']",
                "input[type='password']",
                "#s-lc-auth-pin",
                "input[id*='pin']",
            ]

            pin_input = None
            for selector in pin_selectors:
                try:
                    pin_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if pin_input.is_displayed():
                        break
                    pin_input = None
                except NoSuchElementException:
                    continue

            if pin_input and account.pin:
                pin_input.clear()
                pin_input.send_keys(account.pin)
                log.info("Entered PIN")
            elif not account.pin:
                log.warning("No PIN set for this account! Please enter PIN manually or update config.")
                input(">>> Press Enter after manually entering your PIN...")

            self._slow()

            # Click login button
            login_selectors = [
                "button[type='submit']",
                "input[type='submit']",
                "#s-lc-auth-login",
                "button.btn-primary",
            ]
            login_xpaths = [
                "//button[contains(text(), 'Log In')]",
                "//button[contains(text(), 'Login')]",
                "//button[contains(text(), 'Sign In')]",
                "//input[@value='Log In']",
                "//input[@value='Login']",
            ]

            for selector in login_selectors:
                try:
                    btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if btn.is_displayed():
                        btn.click()
                        log.info("Clicked login button")
                        time.sleep(3)
                        return True
                except (NoSuchElementException, ElementClickInterceptedException):
                    continue

            for xpath in login_xpaths:
                try:
                    btn = self.driver.find_element(By.XPATH, xpath)
                    if btn.is_displayed():
                        btn.click()
                        log.info("Clicked login button")
                        time.sleep(3)
                        return True
                except (NoSuchElementException, ElementClickInterceptedException):
                    continue

        else:
            log.info("No login form detected (might already be authenticated)")
            return True

        return False

    # ── Booking Form ──────────────────────────────────────────────────────

    def fill_booking_form(self) -> bool:
        """Fill in the booking form after authentication."""
        time.sleep(3)

        # Accept Terms & Conditions if present
        try:
            tc_selectors = [
                "input[type='checkbox'][id*='terms']",
                "input[type='checkbox'][id*='tc']",
                "input[type='checkbox'][name*='terms']",
                "#s-lc-eq-tc",
                "input[type='checkbox']",
            ]
            for selector in tc_selectors:
                try:
                    checkbox = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if checkbox.is_displayed() and not checkbox.is_selected():
                        checkbox.click()
                        log.info("Accepted Terms & Conditions")
                        break
                except NoSuchElementException:
                    continue
        except Exception as e:
            log.warning(f"T&C handling: {e}")

        self._slow()
        return True

    def final_submit(self) -> bool:
        """Click the final 'Submit my Booking' button."""
        submit_selectors = [
            "#s-lc-eq-bsubmit",
            "#btn-form-submit",
            "button.btn-primary",
            "button[type='submit']",
            "input[type='submit']",
        ]
        submit_xpaths = [
            "//button[contains(text(), 'Submit my Booking')]",
            "//button[contains(text(), 'Submit Booking')]",
            "//button[contains(text(), 'Confirm')]",
            "//input[contains(@value, 'Submit')]",
            "//button[contains(text(), 'Reserve')]",
            "//button[contains(text(), 'Book')]",
        ]

        for selector in submit_selectors:
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    log.info(f"Final submit clicked: {selector}")
                    time.sleep(5)
                    return True
            except (NoSuchElementException, ElementClickInterceptedException):
                continue

        for xpath in submit_xpaths:
            try:
                btn = self.driver.find_element(By.XPATH, xpath)
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    log.info(f"Final submit clicked: {xpath}")
                    time.sleep(5)
                    return True
            except (NoSuchElementException, ElementClickInterceptedException):
                continue

        log.error("Could not find final submit button!")
        self._screenshot("no_final_submit")
        return False

    def check_booking_success(self) -> bool:
        """Check if the booking was confirmed."""
        time.sleep(3)
        page_source = self.driver.page_source.lower()

        success_indicators = [
            "booking confirmed",
            "reservation confirmed",
            "successfully booked",
            "booking has been confirmed",
            "your booking",
            "confirmation",
            "thank you",
            "booked successfully",
        ]

        for indicator in success_indicators:
            if indicator in page_source:
                log.info(f"✅ Booking confirmed! (matched: '{indicator}')")
                return True

        # Check for error messages
        error_indicators = [
            "error",
            "failed",
            "unavailable",
            "already booked",
            "conflict",
            "maximum",
            "limit reached",
        ]

        for indicator in error_indicators:
            if indicator in page_source:
                log.warning(f"⚠️  Possible booking issue (matched: '{indicator}')")

        self._screenshot("booking_result")
        return False

    # ── Main Booking Flow ─────────────────────────────────────────────────

    def book_room(
        self,
        account: Account,
        room: Room,
        target_date: str,
        preferred_time: str = None,
    ) -> BookingResult:
        """
        Complete booking flow for one room with one account.
        
        Steps:
        1. Navigate to room availability page
        2. Select date
        3. Select time slot(s)
        4. Submit time selection
        5. Authenticate with library card
        6. Fill booking form
        7. Submit final booking
        """
        log.info("=" * 60)
        log.info(f"BOOKING: {room.name}")
        log.info(f"  Account: {account.name} ({account.library_card})")
        log.info(f"  Date: {target_date}")
        log.info(f"  Preferred time: {preferred_time or 'any available'}")
        log.info("=" * 60)

        result = BookingResult(
            success=False,
            account=account.name,
            room=room.name,
            date=target_date,
            time_slot=preferred_time or "any",
        )

        try:
            # Step 1: Navigate to room
            self.navigate_to_room(room, target_date)

            # Step 2: Select time slots
            if not self.select_time_slots(preferred_time, self.prefs["booking_duration_hours"]):
                result.message = "No available time slots found"
                log.error(result.message)
                return result

            # Step 3: Submit time selection
            if not self.submit_times():
                result.message = "Failed to submit time selection"
                log.error(result.message)
                return result

            # Step 4: Authenticate
            if not self.authenticate(account):
                result.message = "Authentication failed"
                log.error(result.message)
                return result

            # Step 5: Fill booking form
            self.fill_booking_form()

            # Step 6: Final submit
            if not self.final_submit():
                result.message = "Failed to submit final booking"
                log.error(result.message)
                return result

            # Step 7: Check success
            result.success = self.check_booking_success()
            result.message = "Booking confirmed!" if result.success else "Booking status unclear"

        except Exception as e:
            result.message = f"Error: {str(e)}"
            log.exception(f"Booking failed: {e}")
            self._screenshot("exception")

        return result

    # ── Batch/Auto Booking ────────────────────────────────────────────────

    def auto_book(self, target_date: str = None, preferred_time: str = None):
        """
        Auto-book rooms for both accounts.
        
        Strategy:
        - Account 1 → Group Study Room 1 (2 hours)
        - Account 2 → Group Study Room 2 (2 hours)
        This gives you 2 rooms × 2 hours = up to 4 hours of room time
        """
        if not target_date:
            # Default: book the furthest day out (4 days ahead)
            target_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")

        log.info(f"\n{'='*60}")
        log.info(f"AUTO-BOOKING for {target_date}")
        log.info(f"{'='*60}\n")

        # Pair accounts with rooms
        bookings = []
        for i, (account, room) in enumerate(zip(self.accounts, self.rooms)):
            if not account.pin:
                log.warning(f"Skipping {account.name}: no PIN set")
                continue

            time_pref = preferred_time or self.prefs["preferred_times"][0]
            result = self.book_room(account, room, target_date, time_pref)
            bookings.append(result)

            # Clear cookies between accounts
            if i < len(self.accounts) - 1:
                log.info("Clearing session for next account...")
                self.driver.delete_all_cookies()
                time.sleep(2)

        # Summary
        log.info("\n" + "=" * 60)
        log.info("BOOKING SUMMARY")
        log.info("=" * 60)
        for b in bookings:
            status = "✅ SUCCESS" if b.success else "❌ FAILED"
            log.info(f"  {status} | {b.account} | {b.room} | {b.date} {b.time_slot}")
            if b.message:
                log.info(f"    → {b.message}")
        log.info("=" * 60)

        self.results = bookings
        return bookings

    def cron_book(self):
        """
        Designed to run daily via cron/Task Scheduler.
        Books the maximum days ahead for both accounts.
        """
        target_date = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
        log.info(f"[CRON] Auto-booking for {target_date}")
        return self.auto_book(target_date)


# ─── Interactive Mode ─────────────────────────────────────────────────────────

def interactive_mode(config: dict):
    """Interactive CLI for manual booking control."""
    booker = SJPLBooker(config)

    print("\n" + "=" * 50)
    print("   SJPL Study Room Booker - Interactive Mode")
    print("=" * 50)
    print(f"\nAccounts loaded:")
    for i, acct in enumerate(config["accounts"]):
        pin_status = "✅ PIN set" if acct["pin"] else "❌ No PIN"
        print(f"  {i+1}. {acct['name']} ({acct['library_card']}) - {pin_status}")

    print(f"\nTarget rooms:")
    for i, room in enumerate(config["target_rooms"]):
        print(f"  {i+1}. {room['name']} (ID: {room['space_id']})")

    print(f"\nBookable dates:")
    for d in range(1, 5):
        date = (datetime.now() + timedelta(days=d)).strftime("%Y-%m-%d (%A)")
        print(f"  {d}. {date}")

    # Get user input
    print()
    date_choice = input("Enter date (YYYY-MM-DD) or days ahead (1-4) [4]: ").strip() or "4"
    if date_choice.isdigit() and len(date_choice) <= 1:
        target_date = (datetime.now() + timedelta(days=int(date_choice))).strftime("%Y-%m-%d")
    else:
        target_date = date_choice

    time_choice = input("Preferred start time (HH:MM) or press Enter for any: ").strip() or None

    acct_choice = input("Account (1/2/both) [both]: ").strip() or "both"

    print(f"\n📅 Booking for: {target_date}")
    print(f"⏰ Time: {time_choice or 'first available'}")
    print(f"👤 Account(s): {acct_choice}")
    confirm = input("\nProceed? (y/n) [y]: ").strip().lower() or "y"

    if confirm != "y":
        print("Cancelled.")
        return

    # Start booking
    booker.start()
    try:
        if acct_choice == "both":
            booker.auto_book(target_date, time_choice)
        else:
            idx = int(acct_choice) - 1
            account = booker.accounts[idx]
            room = booker.rooms[min(idx, len(booker.rooms) - 1)]
            result = booker.book_room(account, room, target_date, time_choice)
            print(f"\nResult: {'✅ Success' if result.success else '❌ Failed'} - {result.message}")
    finally:
        input("\nPress Enter to close browser...")
        booker.stop()


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SJPL Branch Study Room Auto-Booker")
    parser.add_argument("--auto", action="store_true", help="Auto-book with defaults")
    parser.add_argument("--cron", action="store_true", help="Cron mode (headless, auto)")
    parser.add_argument("--date", type=str, help="Target date (YYYY-MM-DD)")
    parser.add_argument("--time", type=str, help="Preferred start time (HH:MM)")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--account", type=int, choices=[1, 2], help="Use specific account")
    parser.add_argument("--room", type=int, choices=[1, 2], help="Target specific room (1 or 2)")
    parser.add_argument("--debug", action="store_true", help="Enable slow mode + verbose logging")
    parser.add_argument("--setup", action="store_true", help="Run first-time setup wizard")

    args = parser.parse_args()

    # Load or create config
    config = load_config()

    # Apply CLI overrides
    if args.headless or args.cron:
        config["preferences"]["headless"] = True
    if args.debug:
        config["preferences"]["slow_mode"] = True
        logging.getLogger().setLevel(logging.DEBUG)

    # First-time setup
    if args.setup:
        print("\n=== SJPL Booker Setup ===")
        for acct in config["accounts"]:
            print(f"\nAccount: {acct['library_card']}")
            pin = input(f"  Enter PIN for {acct['name']}: ").strip()
            if pin:
                acct["pin"] = pin
        save_config(config)
        print(f"\n✅ Config saved to {CONFIG_FILE}")
        return

    # Validate PINs
    missing_pins = [a["name"] for a in config["accounts"] if not a["pin"]]
    if missing_pins and (args.auto or args.cron):
        log.error(f"Missing PINs for: {', '.join(missing_pins)}")
        log.error(f"Run: python {sys.argv[0]} --setup")
        sys.exit(1)

    # Execute
    booker = SJPLBooker(config)

    if args.auto or args.cron:
        target_date = args.date or (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
        booker.start()
        try:
            if args.account:
                idx = args.account - 1
                room_idx = (args.room or args.account) - 1
                result = booker.book_room(
                    booker.accounts[idx],
                    booker.rooms[min(room_idx, len(booker.rooms) - 1)],
                    target_date,
                    args.time,
                )
                sys.exit(0 if result.success else 1)
            else:
                results = booker.auto_book(target_date, args.time)
                sys.exit(0 if any(r.success for r in results) else 1)
        finally:
            booker.stop()
    else:
        interactive_mode(config)


if __name__ == "__main__":
    main()
