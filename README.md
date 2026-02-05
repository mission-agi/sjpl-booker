# SJPL Study Room Auto-Booker 📚

Automates booking of **Village Square Branch** study rooms at San Jose Public Library.

## Target Rooms
| Room | Space ID | Capacity |
|------|----------|----------|
| Group Study Room 1 – Village Square | 131580 | 6 |
| Group Study Room 2 – Village Square | 131582 | 8 |

## Accounts
| Account | Library Card |
|---------|-------------|
| Account 1 | 211xxxxxxxxxxx |
| Account 2 | 211xxxxxxxxxxx |

## SJPL Booking Rules
- Max **2 hours** per day per account
- Book up to **4 days** in advance
- Must show up within **15 minutes** or forfeit

## Setup

### 1. Install Python dependencies
```bash
pip install selenium webdriver-manager
```

### 2. Install Chrome browser (if not already installed)
The script uses Chrome via Selenium. Make sure Google Chrome is installed.

### 3. Set your PINs
```bash
python sjpl_booker.py --setup
```
This will prompt you for PINs and save them to `sjpl_config.json`.

Or manually edit `sjpl_config.json` and fill in the `"pin"` fields.

## Usage

### Interactive mode (recommended first time)
```bash
python sjpl_booker.py
```
Walks you through date, time, and account selection with a visible browser.

### Auto-book (both accounts, 4 days ahead)
```bash
python sjpl_booker.py --auto
```

### Book a specific date and time
```bash
python sjpl_booker.py --auto --date 2026-02-09 --time 10:00
```

### Book with a specific account only
```bash
python sjpl_booker.py --auto --account 1 --date 2026-02-09
```

### Headless mode (no browser window)
```bash
python sjpl_booker.py --auto --headless
```

### Debug mode (slow with extra logging)
```bash
python sjpl_booker.py --debug
```

## Scheduling (Daily Auto-Book)

### macOS/Linux — cron
```bash
# Edit crontab
crontab -e

# Run daily at 6 AM to book 4 days ahead
0 6 * * * /usr/bin/python3 /path/to/sjpl_booker.py --cron
```

### Windows — Task Scheduler
1. Open Task Scheduler
2. Create Basic Task → "SJPL Room Booker"
3. Trigger: Daily at 6:00 AM
4. Action: Start Program → `python` with argument `C:\path\to\sjpl_booker.py --cron`

## Strategy: Maximize Room Time

With 2 accounts you can book **4 hours** of study rooms per day:

| Time | Room 1 (Account 1) | Room 2 (Account 2) |
|------|-------|-------|
| 10:00–12:00 | ✅ Booked | ✅ Booked |

Or chain them **back-to-back** in the same room:

| Time | Room 1 |
|------|--------|
| 10:00–12:00 | Account 1 |
| 12:00–14:00 | Account 2 |

## Troubleshooting

- **"No available time slots found"** — The room may be fully booked. Try a different time or date.
- **Screenshots** — Check `screenshot_*.png` files for visual debugging.
- **Logs** — Check `sjpl_booker.log` for detailed output.
- **Stale browser** — Delete any leftover Chrome processes and retry.
- **CAPTCHA** — If the site adds CAPTCHA, you'll need to run in non-headless mode and solve manually.

## Files
```
sjpl_booker.py      — Main automation script
sjpl_config.json    — Configuration (accounts, rooms, preferences)
sjpl_booker.log     — Runtime log
screenshot_*.png    — Debug screenshots
```
