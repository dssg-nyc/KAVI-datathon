# Reach prototype spot check (in progress)

PROTOTYPE notes for `reach-prototype.html`. Goal: compare the prototype's minutes with the MTA trip
planner (mta.info, "Plan a Trip") for the same origin and resource, leaving Tue 10/27/2026 10:00 AM.
The MTA column is not filled in yet.

Prototype settings: bus + subway, up to 2 transfers, default assumptions in
`finder/reach-prototype-engine.js` (`DEFAULTS`).

| # | Origin | Resource (Supabase `public.resources`) | Straight line | Prototype | Prototype, wheelchair | MTA | MTA, Accessible Trip |
|---|---|---|---|---|---|---|---|
| 1 | 2501 Grand Concourse, Bronx | NYC Bar Legal Referral Service, 42 West 44th Street, New York 10036 | 13.9 km | 45 min (D) | 56 min (4) | | |
| 2 | 2101 Church Avenue, Brooklyn | DYCD, 2 Lafayette Street, New York 10007 | 8.0 km | 37 min (Q, J) | 40 min (B, 4) | | |
| 3 | 161-04 Jamaica Avenue, Queens | OBT Bushwick Office, 25 Thornton Street, Brooklyn 11206 | 12.3 km | 44 min (J) | 47 min (J) | | |
| 4 | 10 Richmond Terrace, Staten Island | Project Hospitality Main Office, 100 Park Avenue, Staten Island 10302 | 4.8 km | 40 min (S40) | 42 min (S40) | | |
| 5 | 1 Centre Street, Manhattan | Youth Justice Network Bronx Office, 424 East 147th Street, Bronx 10455 | 13.4 km | 41 min (5) | 43 min (5) | | |
| 6 | 41-17 Main Street, Flushing | Safe Horizon Streetwork Harlem, 209 West 125th Street, New York 10027 | 11.6 km | 68 min (7X, E, D) | 73 min (7X, F, D) | | |
| 7 | 1700 Pitkin Avenue, Brooklyn | ACE Programs for the Homeless, 30-30 Northern Blvd, Long Island City 11101 | 9.3 km | 67 min (L, G) | 84 min (B14, L, F) | | |
| 8 | 1600 Westchester Avenue, Bronx | Mobilization for Justice Bronx, 424 East 147th Street, Bronx 10455 | 4.0 km | 29 min (6) | 34 min (Bx4, 2) | | |

## Getting the MTA times

The mta.info trip form is a Vue component (it has a `goToTripPlannerPage` method). Its
date and time live in the component's `tripDate`, not in the visible date box, so typing a date
into the box still plans for today. That gives "the selected date and time is in the past"
errors. Setting `tripDate` and `accessible` on the component, then calling `planTrip()`, should
work. Results open at `/tripplanner/results/{from name}/{from id}/{to name}/{to id}/{unix time}/{A|D}/...`.
