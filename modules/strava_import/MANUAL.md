# Strava import

## What it does

Reads the zip you download from Strava ("Download your data") and brings it into
fit-push: activities you don't have yet are imported, and the ones you already have
(uploaded earlier from your watch or bike computer) are recognised and updated with what
you set on Strava: the title, the sport type, the bike or shoes, the commute flag, the
description and your private note.

## How to use

1. On strava.com open **Settings → My Account → Download or Delete Your Account →
   Request your archive**, and download the zip from the e-mail Strava sends.
2. Open the **Strava import** page and choose the zip in **Export zip**.
3. Under **Bring over**, untick what you don't want (for example **Titles** if you
   prefer your own names).
4. Click **Preview**. Nothing changes yet: the report shows how many activities are
   already here, how many would be imported, and every change per activity.
5. Click **Import** to apply. Large exports take a few minutes. Reload the page
   afterwards so the activity list shows the new activities and titles.
6. Open an activity: the **Strava** card shows its description, private note and an
   **Open on Strava** link. Bikes and shoes appear on the **Gear** page (with the
   **Gear** module) with the default sports you chose on Strava.

Running the import again with a newer export is safe: activities are never imported
twice and only real changes are applied.

## Limitations

- An activity is recognised when the file is identical or starts within 60 seconds of
  one you have; activities without a file on Strava (entered by hand) are skipped.
- A plain Strava "Ride" never replaces a more specific sport you already have (road,
  gravel or mountain biking).
- Activity types are understood in English and Polish exports; other types are listed
  in the report and the sport is left as it is.
- Photos, comments, kudos, segments, routes and clubs are not imported.
- Gear needs the **Gear** module; imported gear assignments count as a manual choice.
