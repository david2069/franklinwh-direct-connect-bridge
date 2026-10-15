# Keeping your Home Assistant history

You are switching to this bridge, or reinstalling it, and you do not want to lose months of
energy graphs. This page is the honest version of what is possible.

**Read the recommendation first.** The safest course is the one that moves no data.

---

## The short answer

| What you want | What to do | Risk |
| :--- | :--- | :--- |
| Keep the graphs going | **Keep the entity id.** Home Assistant carries history and long-term statistics across an entity-id rename. | Low |
| Start clean, keep the old graphs as history | Leave the old entities alone. New sensors, new series, old graphs still readable. | None |
| Merge an old series into a new one | Manual statistics import, below. | **High — discouraged** |

**We strongly discourage the third.** Importing or merging statistics writes directly into
Home Assistant's long-term statistics database. It is not something this bridge does, it is
not something it can undo for you, and a mistake is discovered weeks later as a wrong number
on the Energy dashboard rather than as an error at the time. If you do it anyway, take a
backup first — a full Home Assistant backup, not a snapshot of one table.

---

## 1. Keep the entity id (recommended)

This is built into Home Assistant and copies nothing. The steps are in
[INSTALL.md → Reinstalling](../INSTALL.md#reinstalling-read-this-before-you-remove-anything).

In short: free the old entity id (delete or rename the old entity), then rename the new
entity to that id. Home Assistant moves history and long-term statistics with the id.

It works when the two sensors mean the same thing, in the same units, with the same
`state_class`. It does **not** work by unit alone — see *What makes a series mergeable*.

---

## 2. Start clean (also recommended)

Do nothing. The old entities keep their history and stay readable in History and in old
dashboards; the new ones start their own series. The Energy dashboard shows a seam on the
day you switched.

This is the only option with no way to get it wrong, and for most people the seam is a
smaller cost than they expect.

---

## 3. Manual statistics import (discouraged)

If you genuinely need one continuous series — a tariff year, a warranty claim, an export to
an accountant — Home Assistant has the tools, and they are **not ours**:

- **Developer Tools → Statistics** (built in). Lists entities with statistics problems and
  lets you **adjust a single sum**. This is the right tool for the common case: the new
  sensor's running total starts from a different number, so the Energy dashboard shows one
  large step. Fix the step, do not import anything.
- **[Spook](https://spook.boo/)** (custom integration, HACS) — provides a
  `recorder.import_statistics` service.
- **[Import Statistics](https://github.com/klausj1/homeassistant-statistics)** (custom
  integration, HACS) — imports statistics from a spreadsheet.

**Not verified by this project.** We have not tested either custom integration against this
bridge's entities, and we do not document their service fields here — follow their own
documentation, which is maintained by their authors and will be current when this page is
not. They write to the recorder database; treat them as you would any tool that does that.

---

## What makes a series mergeable

Matching units are not enough. Before joining anything, check all four:

| | Why it matters |
| :--- | :--- |
| **Same meaning** | "Home load" from the cloud and "home load" from the gateway may be measured at different points. |
| **Same unit** | kWh to kWh. A Wh-to-kWh join is off by 1000 and looks plausible. |
| **Same `state_class`** | `total_increasing` to `total_increasing`. Mixing in a `measurement` sensor produces statistics Home Assistant cannot sum. |
| **Same accumulation window** | **This is the one that catches people.** A *daily* counter that resets at midnight is not the same series as a *lifetime* counter that never does — joining them produces a number that is wrong every day and obviously wrong to nobody. |

This bridge's energy sensors are **daily**: `solar_today_kwh`, `grid_import_today_kwh`,
`load_today_kwh` and so on (`publish/entities.py`), published as kWh with
`state_class: total_increasing`. Before joining one to a sensor from another integration,
establish whether that sensor is daily or lifetime. If you cannot establish it, do not join
them.

---

## A note on `total_increasing`

Home Assistant treats a **drop** in a `total_increasing` sensor as a meter reset and handles
it on its own. A **rise** — the new sensor starting higher than the old one left off — is
what shows as a step, and what Developer Tools → Statistics exists to correct.

So the common "my graph jumped" case needs a one-off adjustment, not an import.
