# Adventures

## What it does

Groups several activities into one **adventure** and shows them together: one map,
totals for the whole trip, a row per day, the fastest and slowest day (by average
speed), the longest and shortest day, the highest point, the day with the biggest climb,
and averages per day and per activity.

There are two types:

- **Traverse**: one continuous line that goes somewhere (a bikepacking trip, a
  long-distance hike): every activity starts where the previous one ended (within 1 km by
  default), and at least half of them end away from where they started. A loop from the
  camp in between is fine; a gap such as a bus ride makes it multi-day.
- **Multi-day**: every other trip: outings from one base on consecutive days (a ski week,
  a climbing trip from a hut), hikes from trailheads in neighbouring valleys, or moving
  between places with gaps.

The module also looks through your activities and **proposes** adventures it finds.
Activities of different sports can be mixed, and activities tagged `#commute` are
left out unless you change that.

## How to use

1. Open **Adventures** in the navigation bar. Your saved adventures show at once; below
   them, **Proposed adventures** appear when detection finishes ("Looking for adventures
   in your activities…" until then). Each row shows the type, the dates, the number of
   days and activities and the distance. Click **▸** at the start of a row to unfold it:
   you see its activities (each links to the activity) and a small map. **Detect again**
   (top right) looks through your activities once more, for example after an import.
2. Click **Create** on a proposal, keep or change the proposed name (type and dates) and
   click **Create** again.
   Click **Dismiss** to hide a proposal for good (**Show dismissed proposals again**
   brings dismissed ones back).
3. To build one by hand, click **New adventure**, enter a name, then tick the activities
   in the list that opens. Change **from** / **to** to see other dates, and click
   **Save**.
4. In an adventure, the tiles show the totals, the **Highest point**, the **Longest day**,
   the **Biggest climb** (most elevation gain in one day), the fastest and slowest day and
   averages. Click a day tile to show that day on the map. **⚙ Customize** after the
   tiles picks and orders them: tick the tiles, use ↑ ↓, and under **Save for** choose
   **this adventure only** or **every traverse / multi-day adventure** (the default for
   that type). **Reset** goes back to the type's tiles (for one adventure) or to the
   standard tiles (for the type). **Colour by** switches the
   map between **Activity** (each activity its own colour, in day order), **Day** (one
   colour per day) and **Total** (the whole route in one colour), or, like the activity
   map, colours the route by **Elevation**, **Speed** (**Pace** for running and walking) or
   **Heart rate**, light to dark from low to high (the legend shows the range). A measure
   with no data is greyed out. Click **Day 1**, **Day 2**, … or
   a row of the **Per day** table to focus the map on one day; **All days** shows
   everything again. Click a route to open the activity.
5. Use the **Traverse** / **Multi-day** buttons to change the type, **Rename** to change
   the name, **Edit activities** to add or remove activities, and **Delete** (click
   twice) to remove the adventure. Deleting an adventure keeps its activities, and they
   are proposed again (even if you had dismissed a proposal with them before).
6. Click **Detection settings** on the Adventures page to change what is proposed:
   - **Max days without activity between days** (default 1): how many empty days may
     lie between two days of one adventure.
   - **Traverse: each start within … of the previous end** (default 1 km): how close an
     activity must start to where the previous one ended for the trip to count as one
     continuous line.
   - **Same area: a start within … of the trip so far** (default 20 km): how near an
     activity must start to an earlier start or end of the trip to belong to it. Big
     enough for hikes from different valleys of one mountain range.
   - **Same spot: a loop ends within … of its start** (default 2 km): what counts as a
     loop (not point-to-point) and how big a home spot is.
   - **Minimum days** (default 2).
   - **Home: a spot used in this many weeks** (default 15; 0 turns it off) and **Home:
     skip activities starting and ending within …** (default 10 km): activities that
     start and end that close to a home spot are everyday training and are never part of
     a trip. A trip may still start at home (the first day ends away).
   - **Excluded tags** (default `commute`) and **Sports that count** (none ticked = any
     sport).

   Click **Save and detect** to apply (the settings close), or **Restore defaults**.
7. On an activity page, the **Adventure** line under the title links to the adventures
   the activity belongs to, with its day number.

## Limitations

- Detection needs GPS and a start time; activities without GPS can still be added by
  hand (they count in the totals but have no line on the map).
- Days are calendar days of the recorded start time (UTC), so a late-evening activity
  in a far time zone may fall on the next day.
- Activities already in an adventure are not proposed again.
- A place you visit very often (in more weeks than the **Home** setting) counts as home,
  and trips within the home distance of it are not proposed; raise the weeks, lower the
  distance, or create the adventure by hand.
- Trips close to home (within the **Same area** distance) on consecutive days may be
  proposed as one; dismiss them or lower **Same area**.
- Fastest and slowest day compare average speeds, even when the days have different
  sports.
