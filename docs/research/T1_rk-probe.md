# rk-probe: RK3588 DA01 (100.64.0.180), read-only probe from AGX agx02

I probed the board read-only from agx02 on 2026-10-05, between 21:10 and 21:14 BST. The raw outputs are saved in `/tmp/claude-1000/-home-tonyho/b9a1f96f-4259-44f3-959f-d0095d7e5c07/scratchpad/rk-probe/`: ping.txt, route.txt, ts_status.txt, ts_peer.txt, ts_ping.txt, ts_netcheck.txt, eno1.txt, ipinfo.txt, lan_ping.txt, portscan.txt, portscan_pass2.txt, ntp_banner.txt, agx_time.txt, agx_ntp_ref.txt, tools.txt, ss.txt and peer_idle.txt. The scripts used are portscan.py, retry.py and ntp_banner.py.

## Summary
- **Reachability:** the board answers over tailscale only, and only through a DERP relay in London (lhr). There is no direct path. RTT is about 12.6 ms average.
- **LAN:** the board is not on 10.0.0.0/24 at the LAN addresses its own docs give (10.0.0.208 and .209). Neither address answers ARP.
- **Open TCP ports (1-10000):** only 22 (OpenSSH 8.9p1), 111 (rpcbind), 4000 (NoMachine) and 5555 (adbd, which runs as root). None of them speaks HTTP. All DriverAgent ports (5572, 5588-5614, 8010, 8014, and so on) are closed. No ZMQ, RTSP or HTTP service is running.
- **Traffic from the board:** the board sends nothing to this AGX. There were no inbound sockets, and over 15 s with no probe running the tailscale peer counters for the board grew by 0 bytes.
- **Clock offset AGX vs RK: NOT MEASURABLE** read-only. clockdiff is not installed, there is no HTTP Date header, udp/123 does not answer, and there is no status endpoint. The AGX itself is about 31-41 ms ahead of public NTP.
- **Config:** the board config points every endpoint at `agx_host = "10.42.0.1"`, the planned direct Link C cable. This AGX has no 10.42.0.x address, and that route goes to the internet gateway. The board cannot reach this AGX there.

## 1. Latency and path
```
$ ping -c 20 -i 0.2 100.64.0.180
20 packets transmitted, 20 received, 0% packet loss, time 3812ms
rtt min/avg/max/mdev = 9.649/12.556/30.931/4.729 ms

$ ip route get 100.64.0.180
100.64.0.180 dev tailscale0 src 100.64.0.20 uid 1000

$ tailscale ping -c 5 100.64.0.180
pong from rk3588-da01 (100.64.0.180) via DERP(lhr) in 12ms
pong from rk3588-da01 (100.64.0.180) via DERP(lhr) in 12ms
pong from rk3588-da01 (100.64.0.180) via DERP(lhr) in 11ms
pong from rk3588-da01 (100.64.0.180) via DERP(lhr) in 11ms
pong from rk3588-da01 (100.64.0.180) via DERP(lhr) in 17ms
direct connection not established
```
`tailscale status --json`, peer entry for the board:
```
"HostName": "rk3588-da01", "Online": true, "Relay": "lhr", "CurAddr": "", "Addrs": null, "Active": true
DNS rk3588-da01.tailb27fb3.ts.net.  Created 2026-09-28T10:45:38Z  KeyExpiry 2027-03-27T10:45:38Z
```
The AGX's own endpoints are `['140.228.47.249:34355', '10.0.0.130:41641', '172.17.0.1:41641']`, and its nearest DERP is lhr at 17 ms (`tailscale netcheck`: UDP true, MappingVariesByDestIP false).

- The path is relayed through DERP lhr, with no direct UDP path. The board publishes no endpoints (`Addrs: null`), so no direct path can form.
- 100.64.0.180 is missing from the first 30 lines of `tailscale status` that were saved; I took the peer details from the `--json` output instead.

## 2. Link speed and LAN
```
$ cat /sys/class/net/eno1/speed
2500
$ ethtool eno1   (worked without root, apart from "netlink error: Operation not permitted")
	Speed: 2500Mb/s
	Duplex: Full
	Link partner advertised link modes: 10baseT/Half ... 1000baseT/Full 2500baseT/Full
	Link detected: yes
```
- **Physical link:** eno1 runs at 2500 Mb/s full duplex, but it is not what limits this path. All traffic to the board goes out to the internet and through DERP. tailscale0 has MTU 1280.
- **Board's LAN addresses in its docs:** 10.0.0.208 (NetworkManager) and 10.0.0.209 (networkd), on eth0 MAC 8c:32:23:72:b5:ee. Sources: `/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/docs/BRINGUP_REPORT.md:594`, `:807` and `:592`, and `/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/docs/STATUS.md:116`.
- **Ping test:** I pinged only those two addresses.
  ```
  $ ping -c 3 -W 1 10.0.0.208   -> 3 transmitted, 0 received, 100% packet loss
  $ ping -c 3 -W 1 10.0.0.209   -> 3 transmitted, 0 received, +1 errors, 100% packet loss
  10.0.0.208 dev eno1  INCOMPLETE
  10.0.0.209 dev eno1  INCOMPLETE
  ```
- **ARP cache:** both addresses were already FAILED before my pings. No entry for MAC 8c:32:23:* is in `/proc/net/arp`.
- **Conclusion:** the board is not on the 10.0.0.0/24 LAN at its documented addresses. This matches tailscale finding no direct path.

## 3. Clock offset AGX vs RK
| Method | Result |
|---|---|
| (a) clockdiff | Not installed: `/usr/bin/clockdiff (No such file or directory)`, no `iputils-clockdiff` package. No other ICMP-timestamp tool is available (hping3, nping and nmap are absent). |
| (b) HTTP Date header | No HTTP port is open on the board (see section 4), so there is no Date header. |
| (c) Status endpoint with a time | None exists, since no HTTP or ZMQ port is open. |
| (d) NTP udp/123 | No answer: `100.64.0.180 try1/2/3: TimeoutError: timed out` (2 s each). |

- **Result:** the RK clock offset is NOT MEASURABLE read-only from here. The SSH banner (section 5) carries no time. TCP timestamps are also unusable, because Linux randomises the timestamp offset per connection and the path goes through tailscaled.
- **What the docs say about the RK clock:** systemd-timesyncd is synchronised to ntp.ubuntu.com, the RTC is an hym8563, and the timezone is Asia/Shanghai (`/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/docs/BRINGUP_REPORT.md:1561`). I could not check this now.

AGX time sync state:
```
$ timedatectl show / timesync-status
NTP=yes  NTPSynchronized=yes  Timezone=Europe/London
Server: 83.217.166.45 (1.pool.ntp.org)  Stratum: 1  Reference: GPS
Poll interval: 34min 8s   Offset: +44.795ms  Delay: 13.916ms  Jitter: 47.820ms  Frequency: -6.632ppm
systemd-timesyncd active; chrony/chronyd/ntp inactive (no chronyc)
```
I cross-checked the AGX clock with my own SNTP client (3 tries per server; values are server minus AGX):
```
83.217.166.45 (str1 GPS): -41.1 / -40.4 / -38.9 ms (delay 12-15 ms)
time.google.com (str1):   -32.5 / -31.3 / -31.2 ms
time.cloudflare.com:      -32.5 / -32.7 / -33.9 ms
0.pool.ntp.org (str2):    -31.4 / -31.4 / -32.9 ms
```
The AGX clock is about 31-41 ms ahead of UTC, with an uncertainty of about ±8 ms (half the round-trip delay). timesyncd reports 47.8 ms of jitter.

## 4. Open TCP ports
Every test was a connect followed by an immediate close.

- **Named list** (59 ports, 0.5 s timeout): `{'closed(refused)': 56, 'open': 3}`. Open: 22, 4000, 5555. Every other port returned ECONNREFUSED, including 80, 443, 554, 8554, 5572, 5588, 5592, 5593, 5595, 5600-5614, 6000-6005, 8010 and 8014.
- **Sweep 1-10000** at 200 concurrent connects: 4 open (22, 111, 4000, 5555), 9756 refused, and 240 `timeout/EAGAIN`.
- **Second sweep** at 50 concurrent connects with a 1.5 s timeout: `{'111': 9996, '0': 4}`, then each of the 4 ports confirmed serially. The 240 timeouts in the first sweep were artefacts of the high concurrency, not filtered ports.

Final list of open ports: **22, 111, 4000, 5555**. This matches the vendor listeners the RK bring-up report found: sshd on 22, rpcbind on 111, NoMachine on 4000, and adbd as root on 5555 (`/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/docs/BRINGUP_REPORT.md:1518`, `:1542-1545`). The vendor services are therefore still running and reachable over tailscale. The plan to disable them, `owner_services.sh`, is still unchecked at `/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/docs/STATUS.md:115`.

## 5. Per-port details
For each port I read for 2 s without sending anything:
```
22   recv 42 bytes after 37 ms: b'SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.17\r\n'
111  no bytes within 2 s
4000 no bytes within 2 s
5555 no bytes within 2 s
```
- **HTTP:** none of the open ports is HTTP, so I ran no curl and no `/api/health`, `/api/status`, `/status` or `/health` GETs. The ports 80, 443, 8000, 8080 and 8888 all refused the connection. I sent nothing to 111 or 5555, which are rpcbind and root adbd.
- **RTSP:** 554 and 8554 are closed. The RK repo also defines no RTSP path, so I did not run gst-discoverer.
- **ZMQ:** all ZMQ-looking ports are closed, so there was nothing to SUB to.

## 6. Does the board send anything to this AGX?
```
$ ss -tunap | grep 100.64.0.180
(only TIME-WAIT from my own probes: 100.64.0.20 -> :22/:111/:4000/:5555)
$ ss -uanp  (ports 5572, 5588, 5592-5595, 5600-5614, 6000-6005, 8010, 8014)
State  Recv-Q Send-Q Local Address:Port  Peer Address:PortProcess        <- nothing
$ ss -tlnp  (same ports)                                                  <- nothing listening
$ ss -tan state syn-recv                                                  <- empty
tailscale peer rk3588-da01, 15 s with no probe running: Rx +0 B, Tx +0 B
```
- **Result:** nothing comes from the board. No socket on the AGX listens on any DriverAgent port, so a connect from the board would be refused anyway.
- **What the config says:** in the DriverAgent design the AGX binds every socket and the RK connects to it. All of those connects go to `10.42.0.1`:
  - `/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/boards/rk3588-da01/board.toml:23-24` sets `[hmi.bus] agx_host = "10.42.0.1"`.
  - `/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/config/rk.toml:152` sets `agx_host = "10.42.0.1"`, with the comment "the AGX binds every socket; the RK connects".
  - `/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/config/rk.toml:42` sets `camera_health = "tcp://10.42.0.1:5572"`.
- **Ports the board connects to** at agx_host:
  - Status: hello 5611 (`rk.toml:146`), recorder status 5614 (`rk.toml:115`) and segment events 5613 (`rk.toml:116`).
  - HMI publishers: heartbeat 5595, engage 5608, disengage 5609 and request 5604 (`rk.toml:215-229`).
- **Ports the board subscribes to** at agx_host: autopilot_state 5607, car_state 5592, gps 5588, board_hello_agx 5612, bev_frame 8010 and driver_guard 8014 (`rk.toml:160-200`).
- **Where 10.42.0.1 is supposed to be:** it is the AGX end of a planned point-to-point cable, "Link C", with the AGX at 10.42.0.1/30 on eno1 and the RK at 10.42.0.2/30 (`/home/tonyho/driveragent-agx/ref/driveragent-hmi/RK3588_AGENT_KICKOFF.md:100` and `:139`). The RK side is not configured yet either: "A fixed 10.42.0.2/30 on the board is a proposed change, not made" (`/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/docs/RECOVERY.md:28`). Link C is still pending in the milestone list (`/home/tonyho/driveragent-agx/ref/driveragent-hmi/rk/docs/STATUS.md:45-47`).
- **Why the board cannot reach this AGX at 10.42.0.1:**
  - `ip addr | grep 10.42` on the AGX finds nothing (exit 1).
  - `ip route get 10.42.0.2` gives `via 10.0.0.1 dev eno1`, so traffic would go to the internet gateway, not to the board.
  - The board is not on the AGX's LAN (section 2) and is reachable only through tailscale DERP.
  - Even if the board's ZMQ daemons were running, their connects to tcp://10.42.0.1:<port> would never reach this AGX. They would go to whatever 10.42.0.1 is on the board's own network, or nowhere.
  - The only working path today is the tailscale overlay, 100.64.0.180 to 100.64.0.20. The config does not use it, and no DriverAgent port is open on it.