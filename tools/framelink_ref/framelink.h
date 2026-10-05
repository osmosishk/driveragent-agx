// FrameLink sender reference (header-only, C++17) for the RK3588 agent.
//
// Source of the format: RK repo rk-v0.4.0, RK3588_AGENT_KICKOFF.md M1 + section 4 (40-byte header,
// UDP camN -> 6000+N, 16-byte fragment header, 8896 B chunk at MTU 9000 / 1456 B at MTU 1500).
// The parts that the RK repo does not define are AGX PROPOSALS (docs/RK_AGX_INTERFACE.md section 3):
// magic, fmt codes, source codes 2/3, CRC coverage, fragment header layout.
// The AGX receiver is common/framelink.py. golden_vectors.txt (same folder) is the shared test data:
// test_framelink.cpp must reproduce it byte by byte.
#pragma once

#include <cstdint>
#include <cstring>
#include <vector>

namespace framelink {

constexpr uint32_t kMagic = 0x4B4E4C46;      // PROPOSAL: bytes "FLNK"
constexpr uint8_t kVersion = 1;
constexpr uint16_t kFragMagic = 0x4C46;      // PROPOSAL: bytes "FL"
constexpr uint8_t kFragVersion = 1;
constexpr size_t kHeaderLen = 40;
constexpr size_t kFragHeaderLen = 16;
constexpr size_t kChunkJumbo = 8896;         // RK: MTU 9000
constexpr size_t kChunk1500 = 1456;          // RK BRINGUP proposal: 1472 B UDP payload at MTU 1500
constexpr uint16_t kBasePort = 6000;         // RK: camN -> 6000 + N

enum Fmt : uint8_t { kFmtNv12 = 1, kFmtH265 = 2 };                            // PROPOSAL
enum Source : uint8_t { kSourceLive = 1, kSourceReplay = 2, kSourceTestPattern = 3 };  // 1 = RK
enum Health : uint8_t { kNotStarted = 0, kStarting = 1, kLive = 2, kStalled = 3, kNoSignal = 4 };  // camd LinkState

struct Header {
    uint8_t cam = 0;
    uint8_t fmt = kFmtNv12;
    uint8_t health = kLive;
    uint32_t seq = 0;
    uint64_t t_capture_ns = 0;   // CLOCK_REALTIME until PTP (AGX proposal); PTP time after M3
    uint16_t width = 0;
    uint16_t height = 0;
    uint16_t stride = 0;         // NV12: luma row bytes; H.265: 0
    uint16_t exposure_us = 0;    // 0 = unknown
    uint8_t source = kSourceLive;
};

// CRC-32C (Castagnoli), reflected 0x82F63B78, init/xorout 0xFFFFFFFF: same as the dabus envelope.
inline uint32_t crc32c(const uint8_t* p, size_t n, uint32_t crc = 0) {
    static uint32_t table[256];
    static bool init = false;
    if (!init) {
        for (uint32_t i = 0; i < 256; ++i) {
            uint32_t c = i;
            for (int k = 0; k < 8; ++k) c = (c & 1u) ? (c >> 1) ^ 0x82F63B78u : c >> 1;
            table[i] = c;
        }
        init = true;
    }
    crc ^= 0xFFFFFFFFu;
    for (size_t i = 0; i < n; ++i) crc = table[(crc ^ p[i]) & 0xFFu] ^ (crc >> 8);
    return crc ^ 0xFFFFFFFFu;
}

inline void put16(uint8_t* p, uint16_t v) { p[0] = uint8_t(v); p[1] = uint8_t(v >> 8); }
inline void put32(uint8_t* p, uint32_t v) { for (int i = 0; i < 4; ++i) p[i] = uint8_t(v >> (8 * i)); }
inline void put64(uint8_t* p, uint64_t v) { for (int i = 0; i < 8; ++i) p[i] = uint8_t(v >> (8 * i)); }

// Build header (40 B) + payload. payload_crc32c over the payload; header_crc32c over bytes 0..35
// (these include payload_crc32c, so compute the payload CRC first).
inline std::vector<uint8_t> pack_frame(const Header& h, const uint8_t* payload, size_t n) {
    std::vector<uint8_t> f(kHeaderLen + n);
    uint8_t* b = f.data();
    put32(b + 0, kMagic);
    b[4] = kVersion;
    b[5] = h.cam;
    b[6] = h.fmt;
    b[7] = h.health;
    put32(b + 8, h.seq);
    put64(b + 12, h.t_capture_ns);
    put16(b + 20, h.width);
    put16(b + 22, h.height);
    put16(b + 24, h.stride);
    put16(b + 26, h.exposure_us);
    b[28] = h.source;
    b[29] = b[30] = b[31] = 0;   // reserved
    put32(b + 32, crc32c(payload, n));
    put32(b + 36, crc32c(b, 36));
    if (n) std::memcpy(b + kHeaderLen, payload, n);
    return f;
}

// Split one frame (header + payload) into UDP datagrams: 16-byte fragment header + chunk.
// Fragment header (PROPOSAL): magic u16, ver u8, cam u8, seq u32, idx u16, count u16, offset u32.
// Send the datagrams of one frame PACED over the frame interval (the AGX socket buffer is small).
inline std::vector<std::vector<uint8_t>> fragments(const std::vector<uint8_t>& frame, uint8_t cam,
                                                   uint32_t seq, size_t chunk = kChunkJumbo) {
    std::vector<std::vector<uint8_t>> out;
    const size_t count = (frame.size() + chunk - 1) / chunk;
    if (count == 0 || count > 0xFFFF) return out;
    for (size_t i = 0; i < count; ++i) {
        const size_t off = i * chunk;
        const size_t len = (off + chunk <= frame.size()) ? chunk : frame.size() - off;
        std::vector<uint8_t> d(kFragHeaderLen + len);
        put16(d.data() + 0, kFragMagic);
        d[2] = kFragVersion;
        d[3] = cam;
        put32(d.data() + 4, seq);
        put16(d.data() + 8, uint16_t(i));
        put16(d.data() + 10, uint16_t(count));
        put32(d.data() + 12, uint32_t(off));
        std::memcpy(d.data() + kFragHeaderLen, frame.data() + off, len);
        out.push_back(std::move(d));
    }
    return out;
}

}  // namespace framelink
