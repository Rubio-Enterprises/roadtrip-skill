# Road-trip tools and search sources

1. **Validate names first.** `validate_place` uses the keyless Photon geocoder. Confirm
   suggestions with the traveler before routing.
2. **Measure the drive.** `route` takes ordered [lat, lng] pairs; it tries TomTom, then
   OSRM, then a straight-line estimate. To check which road Google takes, use `route_legs`
   with typical traffic, compare each path to the desired road and read Google's warnings.
   Check request count and billing tier before repeating. Without a Google key it returns
   an error, not another engine's path: use `route` for time and say the road wasn't checked.
3. **Check weather and access.** `weather_forecast` tries NWS (US, ~7 days) then
   Open-Meteo (global, ~16 days). Use `weather_climatology` beyond coverage. Consult
   official park alerts, DOT/511 or Caltrans for closures and Environment Canada on Canadian
   legs. For hikes try AllTrails; for scenic byways use FHWA. Use traveler reports (e.g.
   r/roadtrip, r/nationalparks, RV forums) for leads, not current official conditions.
4. **Check each park.** Use `park_info` for NPS fees and entry units; `reservation_countdown`
   for release dates. Confirm permits, ticket rules and availability on the official system.
5. **Check EV gaps.** Use `ev_corridor` for state of charge and `chargers_near` for fast
   stations near a gap. Confirm with Open Charge Map, PlugShare, ABRP or the operator.
6. **Check each border.** `border_crossing` covers entry and vehicle rules;
   `customs_exemption` covers residents returning home. Use CBP/CBSA for wait times,
   and CBP/CBSA/SAT or Banjercito as applicable for customs and vehicle requirements.
7. **Price the trip.** `fuel_cost` estimates gas or charging; use GasBuddy or a charger
   operator to check prices. `lodging_quote` gives a tier reference and booking links:
   Booking, Airbnb, Google Hotels, KOA, Hipcamp, Recreation.gov and, where available,
   Ctrip city links for China. Use dated quotes rather than treating a reference as booked.

Server keys: `TOMTOM_API_KEY` enables TomTom routing; `GOOGLE_ROUTES_API_KEY` is
required for Google legs. `NPS_API_KEY` enables park lookup; `OCM_API_KEY` improves
charger lookup reliability. Neither weather provider needs a key.

When a source returns `source: fallback`, run its `searchQueries` with the caller's search
capability, starting with `suggestedSources`. If the search can't confirm the figure,
label the estimate or leave it unknown. Hand the plan to the caller.
