# Connect a new AGX unit to an RK3588 board

This document is the same in the two repositories (driveragent on the board, driveragent-agx on the AGX).
You use only the two dashboards. You do not change a file and you do not use a command line.

Before you start:

- The AGX and the board are on the same local network, and the AGX dashboard runs (port 8700).
- The AGX is in bench mode. In vehicle mode the AGX refuses pairing (owner file `config/control.yaml` on the AGX).
- The link settings of the board are not locked (owner file `/etc/driveragent/agx_link_lock` on the board: no file, or
  `locked = false`).

## On the AGX dashboard

1. Open the AGX dashboard: `http://<AGX address>:8700`. Log in.
2. Open the page **Settings**, part **RK link**.
3. Under **This unit**, read the network address of the AGX that the board can reach (for example the LAN address).
4. Push **Make pairing code**. The page shows the code and the time that is left. The code works one time, for
   10 minutes. A new code stops the code before it.

## On the rk console of the board

5. Open the rk console of the board and log in.
6. Open the page **AGX link**, card **Settings** ("AGX units of this board").
7. Push **Add an AGX unit**.
8. Type a **Name** (for example "AGX03"), the **Address** (the address from step 3, or a host name), and the
   **Pairing code** from step 4. Keep the ports: they show the defaults. Open **Advanced: ports** only when the AGX uses
   other ports.
9. Push **Save and pair**. The console saves the unit, sends the code to the AGX and runs the Test at once. The AGX gives
   a control token for this board. The console keeps the token in a file with mode 600; the browser never gets it.
10. Read the result of the Test. Each check shows a result and a reason in plain words: the address answers; the AGX
    dashboard API answers; the pairing code or the stored token is accepted; a status message arrives; the schema
    versions agree; the AGX control mode. The Test changes nothing on the active link. To test again later, push **Test**.
11. When all checks pass, push **Make active** and confirm. The results stop for a short time. The board stops the
    streams to the old unit and starts them to the new unit.
12. Look at the card. In 30 seconds the switch shows "ok" with the number of cameras that give results. When no result
    comes in 30 seconds, the board goes back to the last good unit and the card shows the reason.

## After the connection

13. On the AGX dashboard, **Settings**, **RK link**, the table **Paired boards** shows the board, its address, the time
    of the pairing, the last time the AGX saw it, and the link state.
14. Optional: on the AGX, type an **Accepted board address** and save. Then only that address can control the AGX.
    Empty: each paired board can control it.
15. To stop the video to the AGX for a time, use **Sender OFF** in the card **Settings** of the rk console. **Sender ON**
    starts it again.

## To remove a connection

- On the AGX dashboard, **Settings**, **RK link**, **Paired boards**: push **Remove** and confirm. The token of that board
  stops at once. The rk console shows "not paired" at its next Test, and its control requests are refused.
- On the rk console, **AGX link**, **Settings**: push **Remove** on a unit that is not active. The console deletes its
  token file. The AGX keeps its pairing record until you remove it on the AGX dashboard.
- To pair the same board again, make a new code on the AGX (step 4), and use **Test** with that code (or **Edit** and
  type the code).

## Limits

- The dashboards use plain HTTP on the local network. The pairing code and the control token go over that network in
  clear text. Use the dashboards only on a network that you control.
- One board has one pairing with one AGX. When the board pairs with the same AGX again (for example from a second entry
  of the same AGX), the AGX replaces the old token of that board. The old entry then shows "not paired" at its next Test.
- When no board is paired, the AGX accepts video from each source on the network (as before the pairing function).
- rk-agxlink, the rk console and the AGX use a change at once. rk-camd (camera health), rk-recorder, rk-hmi, rk-hello and
  rk-logger read the AGX address at their start (they connect to AGX bus ports that the AGX does not open today). After a
  change of the active unit, they use the new address at their next start.
