# CipherSlice Post-Phase-13 Roadmap

CipherSlice now has a much stronger planning foundation in place:

- Phase 1: trust, clarity, and safer preview language
- Phase 2: beginner vs advanced workflow shaping
- Phase 3: broader printer and material coverage
- Phase 4: stronger geometry review, fit logic, and scale intelligence
- Phase 5: editable planning and recommendation comparison
- Phase 6: cleaner output truthfulness and slicer handoff framing
- Phase 7: deeper machine and material realism
- Phase 8: stronger geometry intelligence, fit nuance, and risk grouping
- Phase 9: cleaner review UX and information design
- Phase 10: deeper advanced tuning controls
- Phase 11: snapshot, comparison, and iteration tools
- Phase 12: richer printability checks
- Phase 13: interactive preview and orientation support

These are the next 50 optimal build steps from the current state up to the point where real slicer generation and physical printer connection become the main blocker.

## Phase 14: Visual Review Depth

1. Add orientation preset buttons directly inside the 3D preview instead of only using a dropdown.
2. Let users click an orientation suggestion card to focus the 3D preview on that posture.
3. Add a visible build-plate occupancy tint that changes as the part approaches bed limits.
4. Add support-likelihood hotspots so users can visually see where support burden probably lives.
5. Add a likely seam-region overlay that responds to seam-position changes.
6. Add a simple first-layer stability overlay that highlights narrow or risky bed contact zones.
7. Add a scale sanity overlay that makes accidental tiny or huge parts obvious at a glance.
8. Add a visual height-risk treatment for tall and tip-prone parts.
9. Add snapshot thumbnails for “before” and “recommended orientation” comparisons.
10. Add a one-click visual export for demos, reports, and club review.

## Phase 15: Smarter Editable Planning

11. Add a real recommended-vs-current inspector that groups changes by risk instead of one long list.
12. Let users pin a setting as “do not auto-adjust” before geometry refinement runs.
13. Add a stronger “why CipherSlice changed this” explainer beside major recommendations.
14. Add printer-safe guardrails that warn when advanced overrides move into risky ranges.
15. Add an explicit cost/time tradeoff meter for speed, detail, and material changes.
16. Add a stronger beginner-safe summary that hides low-value advanced noise by default.
17. Add a reusable custom profile save/load system for hobbyists and clubs.
18. Add a better side-by-side material comparison workspace with clearer winner language.
19. Add a better side-by-side printer comparison workspace with faster recommendation summaries.
20. Add a “restore only risky settings” action instead of resetting everything.

## Phase 16: Geometry Diagnostics Plus

21. Add detection for isolated islands that may print in midair or start too late.
22. Add detection for very small hole features that likely close up after printing.
23. Add a stronger wall-thickness estimate that compares feature size against nozzle and line width.
24. Add an enclosure-sensitive warp severity model for hotter materials.
25. Add a risk model for large flat tops that may sag or pill owing to sparse support below.
26. Add a more realistic bridge-span estimate tied to printer class and material family.
27. Add a support-removal difficulty estimate for cosmetic vs functional faces.
28. Add a simpler “fragile print zones” summary for beginners.
29. Add a more detailed “fix this by changing orientation / support / wall count” recommendation set.
30. Add a geometry confidence drill-down so users can see what pushed the score down.

## Phase 17: Slicer Handoff Readiness

31. Add slicer-profile export packs for PrusaSlicer-style backends with cleaner naming and versioning.
32. Add a slicer capability check that explains exactly why a configured backend is or is not usable.
33. Add per-printer G-code flavor validation with more human-friendly error messages.
34. Add start/end G-code templates that can be saved for custom machine workflows.
35. Add safer profile packaging for Bambu-, Prusa-, Klipper-, and generic-Marlin-style machines.
36. Add a final pre-slicer checklist screen that proves the plan is ready for deterministic generation.
37. Add a “what the slicer will decide next” explainer so users know where AI stops and slicing begins.
38. Add artifact naming conventions for school, club, and repeat-production jobs.
39. Add a clearer operator handoff bundle that separates preview files from slicer-ready files.
40. Add a deterministic handoff audit trail that records the approved plan, profile, and release path.

## Phase 18: Deployment and Repeat Use

41. Add project save/load so users can return to a job without restarting the workflow.
42. Add a classroom or club demo mode with cleaner defaults and less advanced clutter.
43. Add a repeat-job template mode for printers that get used often by the same group.
44. Add better error recovery when uploads, geometry reads, or preview generation partially fail.
45. Add mobile-safe and Chromebook-safe fallback UI decisions for lighter environments.
46. Add a lighter “quick review” page for users who only need the summary and download path.
47. Add a richer README walkthrough for setting up slicers, custom printers, and deployment.
48. Add a private/public deployment checklist so the site can be hidden or safely shown when needed.
49. Add a “printer connection readiness” dashboard that shows every remaining blocker clearly.
50. Add a final stop-point screen that says the next serious leap is real slicer generation and physical printer access.

## Stop Point

After Step 50, the work stops being mostly software product shaping.

The next blocker becomes real-world execution:

- a trusted slicer backend installed and callable
- printer profiles validated against that slicer
- a real handoff path such as SD card, local connector, or printer API
- a reachable physical printer
- calibration prints and hardware feedback from actual machines
