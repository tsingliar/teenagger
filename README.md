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

### RCS vs. SMS

Each `[teen.<id>]` (and `[parent]`) section can set `channel = rcs` or
`channel = sms`. **Teens default to `rcs`**; the parent defaults to `sms`.
Pick whichever is actually approved/working on your Twilio account --
there's no requirement that everyone use the same channel.

- `channel = sms` sends from `[twilio] from_number`, exactly like before.
- `channel = rcs` sends through a Messaging Service with an RCS sender,
  configured via `[twilio] rcs_messaging_service_sid`. Get this SID from
  Twilio Console -> Messaging -> Services, once you've created a Messaging
  Service and added/verified an RCS sender on it.
- If a person's `channel = rcs` but `rcs_messaging_service_sid` isn't set
  (or is still the placeholder), sending to them fails with a clear error
  message rather than a cryptic Twilio API error -- `validate` and `list`
  still work fine in the meantime, so you're not blocked while RCS approval
  is pending. Set `channel = sms` for anyone you need working right now.

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

For a fuller picture -- every teen's nag/pause state and when Twilio was
last polled for them, plus every chore's status (not just today's) -- use:

```bash
python3 -m teenagger status
```

The "last polled" timestamp on each teen doubles as a health check: if it
says "never" (or hasn't updated in a while) once the launchd agent should
be running, that's a sign the background process isn't actually alive --
check `logs/teenagger.err.log`.

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

### Opt-out keywords: STOP, START, HELP

Teenagger also recognizes the standard SMS opt-out keywords, checked on every
poll alongside DONE:

- **STOP** (also recognizes `stopall`, `unsubscribe`, `cancel`, `end`, `quit`)
  -- pauses all nagging for that teen (no more reminder texts sent to them)
  and immediately texts the parent: "*&lt;teen&gt; replied STOP -- I've
  paused chore reminders for them...*". Nothing is sent back to the teen for
  STOP itself (your Twilio number/messaging service may add its own
  carrier-required opt-out confirmation on top of this -- see note below).
- **START** (also recognizes `unstop`) -- resumes nagging for that teen and
  texts the parent to confirm.
- **HELP** (also recognizes `info`) -- replies directly to the teen with:
  *"Talk to your parent about chores. Text STOP if you want to stop the
  messages."*

Run `python3 -m teenagger list` to see which teens are currently paused.

You (the parent) can also pause/resume from your end without waiting on a
text round-trip:

```bash
python3 -m teenagger pause alex    # same effect as Alex texting STOP
python3 -m teenagger resume alex   # same effect as Alex texting START
```

By default these text the teen to let them know (mirroring the app's own
STOP/START confirmations); pass `--silent` to skip that.

**Note on Twilio's built-in opt-out handling:** if your Twilio number has
"Advanced Opt-Out" enabled (the default for toll-free numbers and most
Messaging Services), Twilio itself intercepts STOP/START/HELP at the
platform level -- it can send its own auto-reply and block your `from_number`
from texting that recipient again, *before* Teenagger's polling ever sees
the message. That's a good safety net, but it means Teenagger's own STOP
handling is a secondary/backup layer, not the only thing standing between a
teen and being blocked. If you want Teenagger's app-level logic to be the
sole authority (e.g. so a "STOP" only pauses that one teen instead of
Twilio blocking the number at the carrier level, or so you can send them a
custom re-engagement text later), check your Messaging Service's opt-out
settings in the Twilio Console.

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
