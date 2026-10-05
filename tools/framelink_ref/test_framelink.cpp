// Checks framelink.h against golden_vectors.txt (written by the AGX receiver codec common/framelink.py).
// Build: g++ -std=c++17 -Wall -Wextra -Werror -O2 -o /tmp/test_framelink test_framelink.cpp
// Run:   /tmp/test_framelink golden_vectors.txt
#include "framelink.h"

#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

static std::vector<uint8_t> unhex(const std::string& s) {
    std::vector<uint8_t> v;
    if (s == "-") return v;
    for (size_t i = 0; i + 1 < s.size(); i += 2) v.push_back(uint8_t(std::stoul(s.substr(i, 2), nullptr, 16)));
    return v;
}

static std::string hex(const std::vector<uint8_t>& v) {
    static const char* d = "0123456789abcdef";
    std::string s;
    for (uint8_t b : v) { s += d[b >> 4]; s += d[b & 15]; }
    return s;
}

int main(int argc, char** argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: %s golden_vectors.txt\n", argv[0]); return 2; }
    const uint8_t check[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
    if (framelink::crc32c(check, 9) != 0xE3069283u) { std::puts("FAIL crc32c check value"); return 1; }
    std::ifstream in(argv[1]);
    std::string line;
    int n = 0, bad = 0;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream ss(line);
        std::string name, payload_hex, frame_hex, frag0_hex, fraglast_hex;
        unsigned cam, fmt, health, source, chunk, nfrags;
        unsigned long seq, w, h, stride, exp_us;
        unsigned long long t_ns;
        ss >> name >> cam >> fmt >> seq >> t_ns >> w >> h >> stride >> health >> exp_us >> source >> payload_hex >>
            frame_hex >> chunk >> nfrags >> frag0_hex >> fraglast_hex;
        framelink::Header hd;
        hd.cam = uint8_t(cam); hd.fmt = uint8_t(fmt); hd.seq = uint32_t(seq); hd.t_capture_ns = t_ns;
        hd.width = uint16_t(w); hd.height = uint16_t(h); hd.stride = uint16_t(stride);
        hd.health = uint8_t(health); hd.exposure_us = uint16_t(exp_us); hd.source = uint8_t(source);
        const auto payload = unhex(payload_hex);
        const auto frame = framelink::pack_frame(hd, payload.data(), payload.size());
        const auto frags = framelink::fragments(frame, hd.cam, hd.seq, chunk);
        const bool ok = hex(frame) == frame_hex && frags.size() == nfrags && hex(frags.front()) == frag0_hex &&
                        hex(frags.back()) == fraglast_hex;
        std::printf("%-14s %s (frame %zu B, %zu fragments)\n", name.c_str(), ok ? "ok" : "FAIL", frame.size(), frags.size());
        ++n;
        if (!ok) ++bad;
    }
    std::printf("%d vectors, %d failed\n", n, bad);
    return (n > 0 && bad == 0) ? 0 : 1;
}
