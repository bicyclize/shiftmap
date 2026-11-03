# Route-level identification of cycleable and bike-and-ride trips from mobile GPS traces

**A decision-support tool for tactical cycling infrastructure**

*Péter Biczók — Város és Mobilitás Intézet / Bicyclize.com, Budapest*

---

## Abstract

Cities that want to shift trips from cars to bicycles and public transport usually measure the wrong thing: aggregate mode share, which says nothing about *which specific journeys* could plausibly move. We present a static, browser-based tool that answers that question directly from mobile GPS traces. Every observed trip is reconstructed as a routed path on the real road and rail networks — never a straight line between origin and destination — and then classified three ways: could it be cycled outright (≤ 5 km); could it be cycled to a station, carried by rail, and cycled again; or cycled to a station, carried by rail, and walked. The bicycle leg is routed on a cycling-specific network that prefers cycleways and refuses streets where cycling is forbidden; the rail leg runs on passenger lines only, with depot and stabling tracks excluded. Because every alternative is a calculated route, the output is spatial: it identifies the small set of corridors and station catchments where a temporary protected lane would capture the most latent demand. Applied to one week of Budapest data (≈ 39,000 anonymised devices, ≈ 1 % of the city's 1.7 million residents), 171,940 of 391,171 A-to-B trips (44 %) were shorter than 5 km, with a further 45,512 and 28,187 trips feasible as bike–train–bike and bike–train–walk respectively. The method runs entirely in a browser with no server, and its inputs — GPS traces, OpenStreetMap, and a public-transit schedule — are available in almost any city. It is designed around an explicit inferential discipline: it reports *which trips could plausibly shift*, never claiming they did, and it favours relative, spatially localised claims over indefensible absolute volumes.

**Keywords:** cycling potential, bike-and-ride, GPS trip data, route reconstruction, tactical urbanism, mode shift

---

## 1. Introduction

The transport-policy case for cycling rests on displacement: people do not take up cycling in the abstract, they switch *specific journeys*. Identifying which journeys those are, and where the supporting infrastructure should go, is therefore the practical core of any mode-shift programme. Aggregate indicators — modal share, kilometres of cycle lane — cannot localise this: they describe the state of the system, not the distribution of unrealised opportunity.

This paper describes a decision-support tool that fills that gap. From anonymised mobile-device GPS traces, the tool reconstructs every trip as a *routed* path on the street and rail networks, and classifies each trip by the alternative modes that could plausibly serve it: cycling alone, cycling to rail and cycling from rail, and cycling to rail and walking. The result is not a mode-share estimate but a *buildable shortlist*: the roads and station catchments where temporary, low-cost infrastructure would reach the largest number of trips that are already, in principle, cyclable.

The tool was developed for Budapest and is intended to be transferable. Two design choices reflect that intent. First, it is entirely static — a single HTML page plus columnar data files — so it runs in any browser, can be hosted on a low-power computer, and imposes no licence or platform cost on an adopting city. Second, its inputs (GPS traces, OpenStreetMap, a GTFS schedule) are commodity data available in almost any municipality.

## 2. Data

Three data sources are required.

**Mobile GPS traces.** One week (May 2023) of anonymised location pings from approximately 38,000 unique devices across the Budapest region, aggregating to 438,995 recorded trips. Each trip is a time-ordered sequence of coordinates attributed to a single device. The panel is approximately 1 % of the city's 1.7 million residents; its use for inference is discussed in Section 3.5.

**OpenStreetMap (OSM).** The road network (all carriageways and their class), the rail network (tram, light rail, metro and heavy rail ways and their service tags), dedicated cycling and pedestrian ways, and turn restrictions. OSM is used both for routing and for the cycling-specific and passenger-only network filters described below.

**Public-transit schedules.** GTFS stop locations for the MÁV heavy-rail and HÉV suburban-rail networks, used to locate the stations that anchor bike-and-ride trips.

## 3. Methodology

### 3.1 Trip reconstruction and network routing

A trip is defined by its origin and destination. Rather than drawing these as straight lines — which is how GPS "OD" data is conventionally visualised and which systematically underestimates the role of the network — every trip is reconstructed by shortest-path routing on the OSM road graph.

The road graph is built in a standard way: coordinates become nodes (deduplicated by rounded position), consecutive vertices of a way become edges, the largest connected component is retained, and degree-2 chains are contracted into single edges carrying a class and a length. Routing cost is *travel time*, computed as edge length divided by a class-specific speed (motorway 100, trunk 80, primary 60, secondary 50, tertiary 45, unclassified 40, residential 30, service and living street 15 km/h). Time-based cost, rather than distance, is what prevents a route from "rat-running" down residential streets to save tens of metres.

Turn restrictions are enforced structurally. Only junctions carrying a restriction are expanded: each incident edge is given its own copy vertex, and zero-weight connectors are added for every *permitted* turn; a forbidden turn has no connector and is therefore unavailable, not merely expensive. Of 5,696 restrictions in the extract, 5,527 were resolved and validated geometrically — 100 % of `no_left_turn` restrictions resolved to movements that are genuinely left turns, and likewise for right and straight bans. The reconstruction achieved a median detour (routed length ÷ straight-line distance) of 1.26 (10th–90th percentile 1.09–1.61), the expected range for road-network routing.

### 3.2 Scenario classification

Each reconstructed trip is then assigned to one or more feasibility classes:

- **bike (direct)** — origin–destination distance ≤ 5 km;
- **bike + train + bike** — origin and destination each within 2.5 km of a rail station, a rail connection exists between those stations, and total trip distance > 8 km;
- **bike + train + foot** — origin within 2.5 km (cycled), destination within 1.3 km (walked), a rail connection exists, and total distance > 8 km.

The thresholds encode an assumption about access and egress tolerance rather than an observed behaviour; they are exposed as parameters in the tool.

### 3.3 The cycling network

The bicycle leg must be routed on a network a person would actually ride, which is not the carriageway network. A separate cycling graph is assembled from the road ways *plus* the dedicated ways the road extract omits — `highway=cycleway`, `path`, `footway`, `pedestrian` — so the route can use real cycling provision. Ways tagged `bicycle=no`, `bicycle=private` or `bicycle=use_sidepath` are refused, and motorways are excluded. Cost is again time, at cycling speeds, so a longer calm street is preferred over a short fast road.

### 3.4 The rail network, filtered to passenger lines

The rail graph is drawn only from ways that carry passenger service. Depot and stabling infrastructure (`service=yard`) and freight branches (`service=spur`) are excluded, as are non-running features such as platform edges and abandoned track. Two consequences follow, both non-obvious and both essential:

1. *The through line at a station is routinely tagged `service=siding`.* Excluding sidings — an apparently natural extension of the filter — fragments the heavy-rail network into several disconnected pieces, because the running line itself is so tagged at stations. Sidings and crossovers are therefore retained.
2. *The guided systems are physically separate.* Tram, metro, HÉV and heavy rail share no passenger track; the only rails that link them are the very depot connections the filter removes. The rail graph is consequently kept as a set of disjoint components, and a rail leg is routed on the single system that best fits both of its stations.

This filter is what removes a class of visually obvious errors: without it, a router freely uses a depot-to-depot link between two metro lines, drawing trips along track no passenger travels.

### 3.5 The alternative path

For every trip in a feasibility class, the tool computes the *actual alternative* — the routed sequence of legs (bike, train, foot) between the trip's true endpoints and the stations it would use. Station ends are rendered as points, so the output shows both the route and the interchange. A leg that cannot be routed is dropped rather than sketched, and the coverage is reported, keeping the tool honest about its reach.

### 3.6 The discipline of inference

The tool's most important design feature is not algorithmic but rhetorical. It classifies *could have been*, never *was*. A distance-and-connectivity filter establishes physical feasibility; it says nothing about why the observed trip was made by car.

The statistical framing matches. The unit of observation is the anonymised device, and the panel is ~1 % of the population. Sampling precision is therefore not the constraint (≈ ±0.2–0.3 percentage points); selection and coverage bias are, at an order of magnitude larger. The tool accordingly makes relative, spatial, share-of-observed claims ("these corridors concentrate the opportunity") and declines absolute ones — city-wide volumes, modal share, or population trip rates — that a 1 % panel cannot support.

## 4. Results

Of 438,995 recorded trips, 391,171 were genuine A-to-B journeys once near-zero-displacement records (loops that return to their start, or records with < 100 m of net travel) were removed. Of these:

- **171,940 (44 %)** were shorter than 5 km — physically cyclable outright;
- **45,512** could be cycled to a station, carried by rail, and cycled again;
- **28,187** could be cycled to a station, carried by rail, and walked.

Because each of these is a reconstructed route, the result is spatial rather than scalar: the tool localises the demand to a small number of arterial corridors and station catchments. This is the property that makes it actionable — a city can see, before investing, that a temporary protected lane on three or four specific streets would reach most of the latent demand, rather than being handed a city-wide percentage.

## 5. Discussion and limitations

Several limitations bound what the tool claims.

**Underground rail is under-detected.** GPS disappears in tunnels, so a metro trip is reconstructed only between surface portals; the rail classifier therefore under-counts metro. Conversely, a bus passenger is indistinguishable from a car user at the track level, since a bus route *is* a road route. The tool's rail/road distinction is consequently described as "follows a guideway" versus "does not", never "transit" versus "car".

**The panel is not the population.** A ~1 % device panel, with an observed weekday/weekend imbalance, cannot support absolute trip volumes or modal-share estimates. The tool's spatial and relative claims are robust to this; its absolute ones are not, and are not made.

**The data are historical.** The analysis uses May 2023 traces; it describes latent opportunity at that time, not current behaviour.

**The two-step use.** The tool's intended role is the first step of a two-step programme: identify who could switch, then reallocate space on multi-lane roads — including safe routes to stations — through temporary, low-cost interventions. The tool supports the first step and scopes the second; it does not, by itself, deliver infrastructure.

## 6. Conclusion

The tool turns a mobile-GPS dataset into a spatially explicit answer to the question that actually drives mode shift: *which trips could be a bike, or a bike and a train, and where would they ride?* By reconstructing every trip as a routed path, by modelling the cycling and passenger-rail networks faithfully, and by refusing to claim more than the data supports, it gives a city a defensible, buildable shortlist instead of an aggregate statistic. Its inputs and its static, cost-free deployment make it transferable to any city that wants to find, rather than assume, its cycling opportunity.

---

*References to be added (SWOV road-safety literature and the Seville mode-shift case are the primary intended citations).*
