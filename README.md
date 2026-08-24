# Teenagger (Iteration 1: macOS CLI + config file)

A CLI + background process that texts your teenager to do their chores,
on a repeating schedule, until they reply **DONE** -- at which point you
get a text saying so (so you can go verify).

This is Iteration 1 of 3:

1. **This one** -- CLI + config file, background process on your Mac, using Twilio.
2. Android app for the parent (native SMS instead of Twilio).
3. Cloud server (Twilio-backed) so nagging works even when your phone is off-grid.

---

## 1. Get a free Twilio account

1. Sign up at https://www.twilio.com/try-twilio (free trial, no charge for testing).
2. In the [Twilio Console](https://console.twilio.com), copy your **Account SID**
   and **Auth Token** from the dashboard.
3. Get a Twilio phone number: Console -> Phone Numbers -> Manage -> Buy a number
   (free trial numbers are fine, and trial accounts include some free SMS credit).
4. **Trial account restriction:** you can only send SMS to phone numbers you've
   verified. Console -> Phone Numbers -> Manage -> Verified Caller IDs -> add
   your own number and your teenager's number. (You can upgrade to a paid
   account later to lift this restriction -- costs are a few cents per text.)

## 2. Install

```bash
cd ~/Documents/teenagger
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Configure

```bash
cp config/teenagger.conf.example config/teenagger.conf
```

Edit `config/teenagger.conf`:

- `[twilio]` -- your Account SID, Auth Token, and Twilio phone number.
- `[parent]` -- your name and phone number (where "done" notifications go).
- `[schedule.default]` -- how often to nag (`interval_minutes`), and quiet
  hours during which no texts are sent.
- `[teen.<id>]` -- one section per teenager, e.g. `[teen.alex]`.
- `[chore.<id>]` -- one section per chore: what it is, which teen, what time
  it's due, which days (optional, defaults to every day), and who to notify
  when it's done. You can override the schedule per-chore too.

The config file format is a standard Linux-style INI file (same style as
`.gitconfig` or systemd unit files) -- see the comments in the example file
for the full field list.

**Keep `teenagger.conf` private** -- it contains your Twilio auth token.
It's already excluded if you set up a `.gitignore` (see below).

## 4. Validate and test

```bash
python3 -m teenagger validate
```

This checks the config file parses and prints out the chores it found.

Send a test text to make sure Twilio is wired up:

```bash
python3 -m teenagger test-sms alex     # or: test-sms parent
```

Run a single nag/check cycle by hand (useful for testing without waiting):

```bash
python3 -m teenagger run --once
python3 -m teenagger list
```

## 5. How nagging works

- Each chore becomes "active" once its `due_time` passes on a day it's due.
- Every `interval_minutes`, Teenagger texts the teen a reminder, unless it's
  currently within quiet hours.
- If `max_hours_after_due` is set (and non-zero), nagging automatically stops
  that many hours after the due time even if never marked done (the chore is
  marked "expired" rather than nagging forever).
- The teen replies **DONE** (case-insensitive; "done", "finished", "did it",
  etc. all work) to the text. Teenagger polls Twilio for that reply, marks
  the chore done, and texts everyone in that chore's `notify` list.
- If a teen has more than one open chore, "DONE" is applied to their most
  recently-due pending one. If you need to be explicit, you (the parent) can
  also mark a chore done by hand:

  ```bash
  python3 -m teenagger done trash
  ```

- Config changes take effect within one tick (default 60s) -- no restart needed.

## 6. Run it in the background (launchd)

The included `launchd/com.tsingliar.teenagger.plist` runs `teenagger run`
continuously, starts it at login, and restarts it if it crashes.

1. Edit the plist if your project folder isn't exactly
   `/Users/tsingliar/Documents/teenagger` (two paths reference it: the Python
   binary under `venv/bin/python3`, and `WorkingDirectory`).
2. Install it:

   ```bash
   cp launchd/com.tsingliar.teenagger.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.tsingliar.teenagger.plist
   ```

3. Check it's running and see logs:

   ```bash
   launchctl list | grep teenagger
   tail -f logs/teenagger.out.log
   ```

4. To stop/uninstall:

   ```bash
   launchctl unload ~/Library/LaunchAgents/com.tsingliar.teenagger.plist
   rm ~/Library/LaunchAgents/com.tsingliar.teenagger.plist
   ```

5. After editing `config/teenagger.conf`, you do **not** need to restart the
   agent -- it re-reads the config every tick. If you edit the plist itself
   (e.g. changed paths), unload/load again.

## 7. Project layout

```
teenagger/
  teenagger/           Python package
    config.py          parses config/teenagger.conf
    models.py           data classes (Chore, Person, Schedule, ...)
    state.py            local JSON state (pending/done/nag counts)
    twilio_client.py     Twilio send + inbound-reply polling
    scheduler.py         the nag loop and "done" detection logic
    cli.py               `teenagger` command-line tool
  config/
    teenagger.conf.example   template -- copy to teenagger.conf
  state/
    teenagger_state.json     runtime state (auto-created, gitignore this)
  launchd/
    com.tsingliar.teenagger.plist
  logs/                 launchd stdout/stderr logs (auto-created)
  requirements.txt
```

## 8. Known limitations of this iteration (fixed in later iterations)

- Polling Twilio for replies (rather than a webhook) means there's up to one
  tick of delay (default: 60s) before a "DONE" reply is noticed.
- If you're not near your Mac (it's asleep, or you're traveling), nagging
  stops -- Iteration 3's cloud server removes this dependency.
- One active pending chore per teen is assumed when matching "DONE" replies
  without an explicit chore ID; this is fine for typical use but can be
  ambiguous if a teen has several chores due before finishing any of them.
