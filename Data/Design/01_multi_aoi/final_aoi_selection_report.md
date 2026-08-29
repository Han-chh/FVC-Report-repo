# Final four AOIs

The frozen set is AOI-00 plus AOI-01 (candidate C10), AOI-02 (C07), and AOI-03 (C09). All environmental numbers are selection descriptors, not experiment results.

## AOI-00 - original study area

AOI-00 remains byte-for-byte unchanged. It is a relatively smooth, grass-dominated plateau domain: median elevation 3865 m, median slope 1.69°, grassland 94.97%, bare/sparse 3.49%, and 2021-2024 historical NDVI median 0.700. It anchors the feature space and preserves comparability with the publication.

## AOI-01 - candidate C10

AOI-01 represents the very dry soil-background end of the admissible plateau gradient: median elevation 3233 m, slope 4.52°, bare/sparse 99.94%, historical NDVI 0.061, negligible water/cropland/built-up. It differs sharply from grass-rich AOI-00 and from the much higher, more vegetated AOI-02. It tests whether common-support FVC agreement transfers into an extremely sparse plateau surface. All required sensor/year preparation assets are verified in GEE.

## AOI-02 - candidate C07

AOI-02 represents a high, rugged alpine grassland: median elevation 4551 m, elevation IQR 366 m, median slope 21.26°, ruggedness 22.75 m, grassland 80.84%, bare/sparse 9.47%, historical NDVI 0.617. It contrasts with AOI-01 in cover and elevation, with AOI-03 in vegetation abundance, and with AOI-00 in terrain. Its 583 km² footprint supports the same expected block structure and has full source-catalog availability.

## AOI-03 - candidate C09

AOI-03 is the cold/high-elevation sparse transition: median elevation 4686 m, elevation IQR 391 m, slope 12.24°, grassland 34.62%, bare/sparse 50.02%, historical NDVI 0.243. It is higher and much sparser than AOI-00, less barren than AOI-01, and less vegetated/less rugged than AOI-02. This fills the intermediate high-cold soil-background regime.

## Why the other seven were not selected

- C01: ineligible - 27.56% cropland and vegetation+bare below 70%; it risks an irrigated/agricultural signal.
- C05: ineligible - 11.33% water, above the fixed 10% ceiling.
- C02: eligible low-elevation dry steppe/bare domain, but after C10 was selected its environmental contribution was redundant relative to the maximin alternatives.
- C03: eligible rugged grassland-bare domain, but its minimum distance to the selected set was lower than C07/C09 at the relevant steps.
- C04: eligible high rugged grassland with 8.43% water, but less separated than the selected high-altitude candidates.
- C06: eligible very high, rugged, dense grassland; C07 supplied a larger minimum distance from the already selected set under the full standardized feature vector.
- C08: eligible high grassland/sparse domain; it lay between C07 and C09 in feature space and did not maximize the minimum distance.

Selection does not claim that the four AOIs exhaust Qinghai environmental variability. It is a preregistered contrast set for product-reference transferability, nested by AOI in future inference.
