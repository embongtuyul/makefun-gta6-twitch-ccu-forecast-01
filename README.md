# GTA VI Twitch CCU Forecast

[![Rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/embongtuyul/makefun-gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/embongtuyul/makefun-gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Entries](https://make.fun/badge/gta6-twitch-ccu-forecast-01/embongtuyul/makefun-gta6-twitch-ccu-forecast-01/entries.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Entry for [gta6-twitch-ccu-forecast-01](https://make.fun/bounty/gta6-twitch-ccu-forecast-01): forecast Grand Theft Auto VI's launch-day Twitch concurrent viewers, hour by hour (hours 2–24, UTC), as five quantiles an hour, from everything recorded up to the end of hour 1.

## How it works

`main.py` (Python 3.13, standard library only) reads the case file and:

1. Normalises every comparable launch's release-day curve by its own hour-1 print, giving scale-free launch-day shapes.
2. Measures how *depressed* the target's hour 1 is next to its pre-release buzz — `r = hour-1 print / highest viewers in the 24 hours before day start` — and keeps only the third of comparables whose `r` matches the target's. A launch whose hour 1 is depressed still has most of its audience to arrive, so its curve climbs much further over the day.
3. Forecasts each hour's median as the 55th percentile of the matched group's log ratios, with a spread from the group's interquartile range (shrunk ×0.8, capped at 0.7), so the quantiles widen honestly over the day.
4. Falls back to a flat hour-1 forecast with a widening spread when no comparable is usable, so every case always produces a valid output.

On the four practice cases it scores a mean pinball loss of **0.172** against the house baseline's **0.387**, beating the baseline on every case, with 90% coverage of 0.913.
