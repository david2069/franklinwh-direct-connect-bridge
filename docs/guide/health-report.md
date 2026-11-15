# Daily health report

Every morning at **07:00 site time** the bridge checks itself and gives one answer: is it
running well, and is anything getting worse? The answer is **green**, **amber** or **red**,
with the reason on the first line. Nothing in the check talks to the aGate or changes the
battery; it reads what the bridge already keeps.

Open it in **Health → Daily report**. **Run now** makes one at once (it is kept, but not
sent); **Earlier reports** opens past ones. Untick **07:00 each day** to stop it.

## What it looks at

Over the last 24 hours, against the 7 days before:

| Part | What it counts |
|---|---|
| Workers | The bridge's background jobs: any crashed or not beating, and restarts. |
| Polls | Per gateway: polls that worked or failed, and reconnects. |
| Alerts | Alerts raised, by kind, and conditions still active now. |
| Log | Warnings and errors grouped by message, with numbers and addresses taken out, so the same failure every few minutes is one line with a count. A pattern is flagged when it is **new**, **growing** (more than twice its usual daily count) or **all day** (in 20 or more of the 24 hours). Passwords and tokens are never copied in. |
| Housekeeping | Database size, log rows, last backup. |

## The colour

- **Red:** a worker crashed or stopped beating, or a critical condition is still active
  (for example the aGate unreachable now). A condition that cleared but nobody
  acknowledged doesn't count.
- **Amber:** a warning condition still active; any error in the log; a warning pattern seen
  10 or more times that is new, growing or all day; or a gateway with 5 % or more of its
  polls failed (of at least 100).
- **Green:** none of those.

## Where it goes

- **Home Assistant:** one notification, which the next report replaces.
- **Phones:** only when the report is amber or red, through the trigger **Daily health
  report amber or red** ([notifications](ha-setup-and-notifications.md)).

Both follow the **Push notifications** switch. If the bridge was off at 07:00, the report
runs on its first minute back.

## The daily snapshot

Just after midnight the bridge also keeps one row per gateway for the day before: the
aGate's daily totals (battery charged and discharged, solar, grid import and export, home
load), the last SoC and the day's alerts, plus a row for the bridge with its alerts,
warnings and errors. These rows are kept for good (about 100 bytes a day per gateway), so
later reports can show trends longer than the bridge's other history keeps.
