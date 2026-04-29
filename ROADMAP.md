# CipherSlice Demo-Finish Roadmap

This roadmap replaces the longer R&D path with a sharper finish plan for a demo-ready product.

CipherSlice already has:

- guided vs advanced workflow separation
- machine and material planning
- geometry review and fit checks
- interactive preview
- approval and release flow
- a verified PrusaSlicer backend path on the local machine

The goal now is not to rival a slicer.

The goal is to finish CipherSlice as a:

- print planning app
- machine/material review layer
- slicer handoff surface
- approval and export tool

## Phase A: Demo Truthfulness

1. Make the app always state whether output is real slicer G-code or planning preview.
2. Show slicer success and slicer failure messages in plain English.
3. Keep fallback output clearly labeled as not printer-ready.
4. Remove any wording that implies real production output when slicing failed.
5. Tighten approval copy so users understand exactly what the checkbox unlocks.
6. Keep dimensions and fit language consistent across all sections.
7. Show scale-correction notes in one obvious place.
8. Make the release page clearly explain what is ready now vs what is still needed.
9. Keep developer-facing setup details downloadable, not front-and-center.
10. Make the review summary readable at a glance for judges and new users.

## Phase B: Demo Polish

11. Keep Beginner simple and continuous on the main flow.
12. Keep Advanced as its own cleaner workspace.
13. Improve the top-level navigation language so it feels more like a product.
14. Reduce visual clutter in long review sections.
15. Keep the 3D preview and fit sections in their own obvious blocks.
16. Make the release page read like a professional handoff screen.
17. Make the output summary more compact and easier to scan.
18. Keep support, adhesion, and risk notes grouped instead of scattered.
19. Improve the visual hierarchy of warnings, success, and blocked states.
20. Make the public-facing app feel clean even when setup is incomplete.

## Phase C: Real Slicer Integration

21. Detect PrusaSlicer reliably on Windows.
22. Allow an explicit Prusa path via environment variable.
23. Build a stable Prusa-style config from the current live plan.
24. Feed STL, OBJ, or 3MF into the slicer through the app path.
25. Capture real G-code output from the slicer process.
26. Surface slicing failures in plain English.
27. Keep one supported “happy path” reliable before adding more printer families.
28. Confirm the output preview comes from real G-code when slicing succeeds.
29. Confirm downloads use the real slicer output instead of fallback output when available.
30. Keep release confidence aligned with the real backend result.

## Phase D: Public Demo Readiness

31. Decide which local flow is solid enough to demonstrate repeatedly.
32. Freeze the feature set for the demo.
33. Test at least two different real mesh files through the local app.
34. Confirm the app can explain failure honestly when slicing fails.
35. Confirm the app can export something useful in both success and failure states.
36. Prepare one simple beginner-friendly demo path.
37. Prepare one stronger advanced-user demo path.
38. Keep screenshots or notes of a successful real slice for backup.
39. Make the README explain what works today.
40. Make the README explain what still depends on local slicer/backend hosting.

## Phase E: Public Backend Hosting

41. Keep Streamlit for the current demo if time is too tight.
42. Decide whether the public backend needs Docker or a more custom Python host.
43. Choose a host that can run Python and installed slicer binaries.
44. Install PrusaSlicer on that host.
45. Point the hosted app to the slicer executable.
46. Test one real upload on the hosted backend.
47. Add a public URL only after the backend result is trustworthy.
48. Keep the current Streamlit public app as a planning/demo branch if needed.
49. Add a cleaner domain later, after the backend host is stable.
50. Treat printer connection as the next milestone after public slicing works.

## Stop Point

After these 50 steps, CipherSlice is no longer “just a mockup.”

It becomes a real planning and slicer-handoff product with:

- real file upload
- real geometry review
- real slicer-backed output on supported paths
- honest preview fallback when the backend fails
- a clean demo story for judges and early users
