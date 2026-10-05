# T4.6 visual check of the result images (coordinator)

Images: `docs/test_results/t4_viewer/cam0.jpg` ... `cam5.jpg` (written by `python -m tools.result_viewer`
at the end of the T4 5-minute run, 23:07). Video: road recording 8003-20251109 (simulator, SIMULATED).
Each image shows the exact FrameLink frame of the result (the result frameSeq equals the image frame seq).

| Camera | What the image shows | Boxes on objects? |
|---|---|---|
| cam0 (front) | Road ahead, parked and moving cars far ahead. Green drivable-area contour on the road. Red lane-line contours on the painted lines. Yellow DTCP waypoints straight ahead, text "virtual perspective, not calibrated; inputs assumed". | YES. The boxes (car 0.38, car 0.50 and more small boxes) are on the distant cars. The masks follow the road and the lane lines. |
| cam1 | Road to the front-left, cars far ahead, buildings, fence, inner mirror. | PARTLY. The boxes on the distant cars are correct. One large box "car 0.38" on the right half covers the fence and the mirror area: FALSE. |
| cam2 | Road to the right, cars far ahead, building. | YES. The boxes are on the distant cars. No false box. |
| cam3 | Fisheye view through a rear window, empty road, building, a jacket. | NO real object. One box "car 0.40" over the building and the jacket: FALSE. |
| cam4 | Black frame (the camera gave no picture in this recording). | No box (correct). |
| cam5 | Black frame (as cam4). | No box (correct). |

Conclusion: on the front camera (the view the model was made for) the boxes are on the objects and the masks
are correct. On side and rear views the clear cars are found, but large false boxes with low scores
(0.38-0.40, threshold 0.30 from the old code) occur near the image edges. Detection on cam1-5 is not
validated (the old stack ran YOLOPX on cam0 only).
