clear all
set more off

import delimited using "rentals.csv", varnames(1) clear encoding("utf-8")

drop if price_suspect == 1
drop if missing(ln_rent, ln_surface, rooms_cat)

capture confirm variable floor_missing
if _rc {
    generate floor_missing = missing(floor)
}
replace ground_floor = 0 if missing(ground_floor)

capture confirm variable county_group
if _rc {
    generate county_group = county
}
encode county_group, generate(county_id)
fvset base frequent county_id

quietly regress ln_rent ln_surface i.rooms_cat ground_floor floor_missing i.county_id
estat hettest
estat ovtest

regress ln_rent ln_surface i.rooms_cat ground_floor floor_missing i.county_id, vce(hc3)
estimates store hedonic

predict ln_fitted, xb
generate resid = ln_rent - ln_fitted
generate expresid = exp(resid)
quietly summarize expresid
scalar smearing = r(mean)
generate fair_rent_eur = exp(ln_fitted) * smearing
generate gap_pct = (price_eur / fair_rent_eur - 1) * 100

summarize fair_rent_eur gap_pct, detail

regress ln_rent ln_surface i.rooms_cat ground_floor floor_missing i.county_id if n_sources > 1, vce(hc3)
estimates store multi_site

estimates table hedonic multi_site, b(%9.4f) se stats(N r2)

export delimited county_id county price_eur fair_rent_eur gap_pct using "fair_values.csv", replace
