# Adventures

## What it does

Groups several activities into one **adventure** and shows them together: one map,
totals for the whole trip, a row per day, the fastest and slowest day (by average
speed), the longest and shortest day, and averages per day and per activity.

There are two types:

- **Traverse**: a chain of tracks, each day continuing near where an earlier one ended
  (a bikepacking trip, a long-distance hike).
- **Multi-day**: several outings from the same base on consecutive days (a ski week,
  a climbing trip from a hut).

The module also looks through your activities and **proposes** adventures it finds.
Activities of different sports can be mixed, and activities tagged `#commute` are
left out unless you change that.

## How to use

1. Open **Adventures** in the navigation bar. Under **Proposed adventures** each row
   shows the type, the dates, the number of days and activities and the distance.
2. Click **Create** on a proposal, keep or change the name and click **Create** again.
   Click **Dismiss** to hide a proposal for good (**Show dismissed proposals again**
   brings dismissed ones back).
3. To build one by hand, click **New adventure**, enter a name, then tick the activities
   in the list that opens. Change **from** / **to** to see other dates, and click
   **Save**.
4. In an adventure, the tiles show the totals. **Colour by** switches the map between
   **Activity** (each activity its own colour, in day order), **Day** (one colour per
   day) and **Total** (the whole route in one colour). Click **Day 1**, **Day 2**, … or
   a row of the **Per day** table to focus the map on one day; **All days** shows
   everything again. Click a route to open the activity.
5. Use the **Traverse** / **Multi-day** buttons to change the type, **Rename** to change
   the name, **Edit activities** to add or remove activities, and **Delete** (click
   twice) to remove the adventure. Deleting an adventure keeps its activities.
6. Click **Detection settings** on the Adventures page to change what is proposed:
   - **Max days without activity between days** (default 1): how many empty days may
     lie between two days of one adventure.
   - **Traverse: next start within … of an end** (default 10 km): how close a start must
     be to where an earlier activity ended.
   - **Multi-day: starts within … of the base** (default 2 km).
   - **Minimum days** (default 2).
   - **Ignore home** (default 8 weeks): a place where you start activities in this many
     different weeks counts as home and does not link activities, so your everyday
     training is not proposed. 0 turns it off.
   - **Excluded tags** (default `commute`) and **Sports that count** (none ticked = any
     sport).

   Click **Save and detect** to apply, or **Restore defaults**.
7. On an activity page, the **Adventure** line under the title links to the adventures
   the activity belongs to, with its day number.

## Limitations

- Detection needs GPS and a start time; activities without GPS can still be added by
  hand (they count in the totals but have no line on the map).
- Days are calendar days of the recorded start time (UTC), so a late-evening activity
  in a far time zone may fall on the next day.
- Activities already in an adventure are not proposed again.
- A trip to a place you visit very often (more weeks than **Ignore home**) is treated as
  home and not proposed; lower the setting or create the adventure by hand.
- Fastest and slowest day compare average speeds, even when the days have different
  sports.
