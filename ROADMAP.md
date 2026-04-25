# CipherSlice Pre-Printer Roadmap

This roadmap tracks the next 50 things to build before the project reaches the point where a real slicer backend and printer access become the main blocker.

## Phase 1: Make the Prototype Honest and Clear

1. Separate preview output from real printer-ready G-code everywhere in the UI.
2. Show a plain-English capability status box after every generated plan.
3. Rename technical release words into beginner-friendly manufacturing language.
4. Make confidence scores explain what is capped and why.
5. Add a visible "not printer-ready yet" label when no slicer backend is connected.
6. Make SD card, manual download, and secure connector paths impossible to confuse.
7. Improve final approval so users understand what they are approving.
8. Add clearer warnings when a download is only a planning preview.
9. Keep internal AI/worker details out of the main customer flow.
10. Move deeper technical explanations into README and developer-only sections.

## Phase 2: Improve Beginner and Advanced Workflows

11. Make Beginner mode feel like click, upload, review, approve.
12. Make Advanced mode expose richer controls without overwhelming beginners.
13. Add X, Y, and Z labels beside width, depth, and height anywhere dimensions appear.
14. Expand advanced controls for walls, layer height, infill, speed, support, adhesion, nozzle, bed, flow, seam, acceleration, and G-code flavor.
15. Add printer-family presets for more Bambu, Prusa, Creality, Anycubic, Voron, Raise3D, and custom machines.
16. Add clearer material presets for PLA, PETG, ABS, ASA, TPU, Nylon, PC, and composites.
17. Add beginner descriptions for every material choice.
18. Add advanced descriptions for how each setting affects strength, time, and risk.
19. Add a one-click "safe defaults" restore button.
20. Add a "compare recommended vs edited" view.

## Phase 3: Better Geometry and Preview Intelligence

21. Improve STL/OBJ/3MF mesh reading and size detection.
22. Detect likely inch-to-millimeter or meter-to-millimeter scale mistakes.
23. Show object dimensions with X/Y/Z labels.
24. Show object fit against the selected printer build volume.
25. Add a stronger visual bed preview.
26. Add a true 3D model preview path.
27. Add rotate, zoom, and inspect controls for the preview.
28. Show overhang and support-risk estimates in the preview.
29. Show wall-thickness and fragile-feature warnings when detectable.
30. Add a "what changed because of this model" explanation.

## Phase 4: Slicer Handoff Preparation

31. Generate cleaner slicer configuration files.
32. Generate slicer command previews for supported slicers.
33. Package the uploaded model, config, handoff contract, and setup notes into one zip.
34. Add OrcaSlicer-specific profile export support.
35. Add PrusaSlicer-specific profile export support.
36. Add CuraEngine research and compatibility notes.
37. Validate which slicer CLI is available on the machine.
38. Show exactly what environment variable is needed for the slicer path.
39. Add a dry-run slicer check that does not require a printer.
40. Parse slicer errors into beginner-friendly fixes.

## Phase 5: Output Review and Safety

41. Add a "before you print" checklist customized to the selected printer and material.
42. Add a line-type summary when real G-code exists, such as walls, infill, supports, travel, and estimated time.
43. Add estimated filament usage when the slicer provides it.
44. Add estimated print time when the slicer provides it.
45. Add stronger warnings for SD card workflows.
46. Add encrypted download explanations that do not overpromise SD card security.
47. Add an operator handoff sheet that a club member can follow at the printer.
48. Add a final review screen that cleanly separates settings, warnings, downloads, and printer handoff.
49. Add test files and repeatable test cases for different STL sizes and printer profiles.
50. Stop at real hardware handoff until a slicer backend, connector, printer access, and operator permission are available.

## The Hard Stop

The project can keep improving planning, UI, previews, slicer setup, and export packaging without a printer. The true hard stop comes when CipherSlice needs to prove that a real printer receives and safely runs the job. At that point, we need at least one real slicer backend and one real printer workflow to test against.
