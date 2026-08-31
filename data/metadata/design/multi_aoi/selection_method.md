# Environmental AOI selection method

Ten candidate geometries were fixed before any new model execution by translating the exact AOI-00 shape in local azimuthal-equidistant metres. Each has 583.13 km² area, the same physical shape/orientation, and 39 expected intersecting 5 km grid cells. All lie fully within the geoBoundaries Qinghai Province polygon.

Environmental features were computed without FCOVER labels or model results:

- Copernicus DEM GLO-90 server-side AOI clips: median/IQR/range elevation, median slope, neighbour elevation-difference ruggedness;
- ESA WorldCover 2021 v200: categorical area fractions;
- MOD13Q1.061: one 16-day NDVI composite closest to 31 July in each of 2021-2024, summarized across four years.

Eligibility was frozen in `selection_rules.yaml`: water ≤10%, snow/ice ≤10%, cropland ≤20%, built-up ≤2%, vegetation+bare ≥70%, complete four-year NDVI/DEM/WorldCover descriptors, and at least 75 km from AOI-00. Selection used standardized environmental features and greedy anchored maximin: starting with AOI-00, choose the eligible candidate maximizing its minimum Euclidean environmental distance to the already selected set. A 150 km minimum centroid separation was enforced when feasible; all three selected steps met it.

Selection order was C10, C07, C09. Their minimum environmental distances at selection were 6.280, 5.834, and 4.378 standardized units; minimum geographic distances were 559.85, 443.26, and 331.46 km. No OLS, FCOVER, 2025 value, prediction error, or significance output was readable by the selection code.

