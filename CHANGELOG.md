# Changes

**0.1.0 — 2026-11-20**

Initial public source and installer package for Windows 11 ARM64 and Canon LBP2900 over USB.

- Install through **Install.cmd**, including Python through WinGet, private rendering libraries, sign-in startup, and elevated queue registration.
- Remove the installation through **Uninstall.cmd**, with confirmation before deleting saved jobs and automatic elevation for queue removal.
- Advertise monochrome, 600 dpi printing through the Microsoft IPP Class Driver.
- Detect USB power and connection changes and update the Windows queue's Offline status.
- Hold interrupted jobs for review and preserve pending jobs across helper restarts.
- Restrict the IPP listener to loopback, reject browser-origin requests, and bound request size, connection count, and unfinished jobs.
- Include native encoder source, deterministic release packaging, binary hashes, third-party notices, and protocol regression tests.
