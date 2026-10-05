# FrameLink reference for the RK3588 sender

The RK agent implements FrameLink TX in rk-camd (C++). These files show the exact bytes that the AGX
receiver (`common/framelink.py`) accepts.

| File | Content |
|---|---|
| `framelink.h` | Header-only C++17 sender reference: `pack_frame()`, `fragments()`, `crc32c()`. |
| `test_framelink.cpp` | Test: reproduce `golden_vectors.txt` byte by byte. |
| `golden_vectors.txt` | 3 vectors written by the AGX codec (NV12 live, H.265 replay with seq wrap, NV12 test pattern). |

Build and run the test (on the RK3588 or on the AGX):

```
g++ -std=c++17 -Wall -Wextra -Werror -O2 -o /tmp/test_framelink test_framelink.cpp
/tmp/test_framelink golden_vectors.txt
```

Expected output: `3 vectors, 0 failed`.

The magic values, the fmt codes, the source codes 2 and 3, the CRC coverage and the fragment header
layout are AGX PROPOSALS. The RK repository (rk-v0.4.0) does not define them. See
`docs/RK_AGX_INTERFACE.md` section 3. If the RK side changes a value, both sides change it together
and the vectors are written again (`tests/test_framelink_golden.py` checks the AGX side).
