# What the fork is for

The homelab runs one pinned copy of `roadtrip-mcp` behind an AI gateway. The server
answers driving-feasibility questions: where a route goes, when a day runs out of
daylight, whether the car can reach a charger, which park reservations open first,
and what changes at a border. The caller plans the trip and keeps it in TREK. The
server does not book travel, write to TREK, or replace a navigation app.

The [workflow](mcp_server/workflow.md) distinguishes designing a route from verifying
a traveler's own route. The [tool guide](mcp_server/tool-guide.md) names sources and
fallbacks. Estimates and seasonal averages must remain distinguishable from current,
verified observations. North America is the planning scope even where an individual
provider has wider coverage.
