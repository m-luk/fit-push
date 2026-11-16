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
  a climbing trip from a hut), or moving between places with gaps.

The module also looks through your activities and **proposes** adventures it finds.
Activities of different sports can be mixed, and activities tagged `#commute` are
left out unless you change that.

## How to use

1. Open **Adventures** in the navigation bar. Your saved adventures show at once; below
   them, **Proposed adventures** appear when detection finishes ("Looking for adventures
   in your activities…" until then). Each row shows the type, the dates, the place (📍,
   filled in as it is found), the number of days and activities and the distance.
   Click **▸** at the start of a row to unfold it: you see its activities (each links to
   the activity) and a small map; **Find place again** repeats the place lookup.
2. Click **Create** on a proposal. The name is proposed from the place found on
   OpenStreetMap as
   `YYYY-MM Park, City` (for example `2026-07 Tatra National Park, Zakopane`); without a
   national park the mountain range takes its place (`2026-08 Julian Alps, Bovec`). When
   nothing is found, the name comes from the type and dates. Keep or change it and click **Create** again.
   Click **Dismiss** to hide a proposal for good (**Show dismissed proposals again**
   brings dismissed ones back).
3. To build one by hand, click **New adventure**, enter a name, then tick the activities
   in the list that opens. Change **from** / **to** to see other dates, and click
   **Save**.
4. In an adventure, the tiles show the totals, the **Highest point**, the **Longest day**
   and the **Biggest climb** (most elevation gain in one day). **Colour by** switches the
   map between **Activity** (each activity its own colour, in day order), **Day** (one
   colour per day) and **Total** (the whole route in one colour), or, like the activity
   map, colours the route by **Elevation**, **Speed** (**Pace** for running and walking) or
   **Heart rate**, light to dark from low to high (the legend shows the range). A measure
   with no data is greyed out. Click **Day 1**, **Day 2**, … or
   a row of the **Per day** table to focus the map on one day; **All days** shows
   everything again. Click a route to open the activity.
5. Use the **Traverse** / **Multi-day** buttons to change the type, **Rename** to change
   the name, **Find place** to look up the park, mountain range and city (and rename the adventure to
   them if you like), **Edit activities** to add or remove activities, and **Delete** (click
   twice) to remove the adventure. Deleting an adventure keeps its activities.
6. Click **Detection settings** on the Adventures page to change what is proposed:
   - **Max days without activity between days** (default 1): how many empty days may
     lie between two days of one adventure.
   - **Traverse: each start within … of the previous end** (default 1 km): how close an
     activity must start to where the previous one ended for the trip to count as one
     continuous line.
   - **Same place: a start within … of an earlier start or end** (default 2 km): how near
     an activity must start to the trip so far to belong to it.
   - **Minimum days** (default 2).
   - **Ignore home** (default 8 weeks): a place where you start activities in this many
     different weeks counts as home and does not link activities, so your everyday
     training is not proposed. 0 turns it off.
   - **Excluded tags** (default `commute`) and **Sports that count** (none ticked = any
     sport).
   - **Use OpenStreetMap for place names** (on by default): see Limitations.

   Click **Save and detect** to apply (the settings close), or **Restore defaults**.
7. On an activity page, the **Adventure** line under the title links to the adventures
   the activity belongs to, with its day number.

## Limitations

- Place names come from OpenStreetMap. To find them, one point in the middle of the
  route (rounded to about 100 m) is sent to the OpenStreetMap Overpass API for each
  proposal shown on the Adventures page (each place is looked up once and remembered),
  and when you click **Find place**. If you click **Create** before the place is found,
  the name comes from the type and dates. Turn off **Use OpenStreetMap for place
  names** in the detection settings to never send anything. The lookup needs an internet
  connection and can take a few seconds; national parks are found when the route's
  middle is inside one or within 25 km of its centre, mountain ranges when it is inside
  one or within 60 km of where OpenStreetMap places the range (often a label point or a
  ridge line, so a large range may be missed or a neighbouring one chosen).
- Detection needs GPS and a start time; activities without GPS can still be added by
  hand (they count in the totals but have no line on the map).
- Days are calendar days of the recorded start time (UTC), so a late-evening activity
  in a far time zone may fall on the next day.
- Activities already in an adventure are not proposed again.
- A trip to a place you visit very often (more weeks than **Ignore home**) is treated as
  home and not proposed; lower the setting or create the adventure by hand.
- Fastest and slowest day compare average speeds, even when the days have different
  sports.
