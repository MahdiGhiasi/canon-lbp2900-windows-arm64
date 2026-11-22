# Security and privacy

The helper binds to **127.0.0.1:16319** and runs under the signed-in Windows account. Printing and status checks use loopback and USB. Installation may contact WinGet, Microsoft, GitHub, and Python's download infrastructure to obtain prerequisites. The helper has no telemetry or cloud printing service.

The administrator prompt is used to register the queue and allow the installing account to update that queue's status. Python, document rendering, and USB communication run with the account's ordinary permissions. Windows printer administrators retain their existing access.

Uninstall.cmd asks for confirmation before removing the queue and deleting saved jobs. Queue removal can request elevation. User-file cleanup runs in the original account, checks the installation path, and unlinks nested directory links without traversing their targets. It stops helper and status-window processes only when their script path and Windows owner match the installation.

The local IPP endpoint has no authentication between processes on the same PC. Other local software and signed-in users can query job titles, submit jobs, or cancel waiting jobs. Use it on a PC whose local accounts and software you trust. Browser-origin requests are rejected, the Host header is restricted to loopback, and the server is restricted to the loopback address.

Requests are limited to 256 MiB, 16 simultaneous connections, and 100 unfinished jobs. Request bodies have a 120-second deadline. The server checks available disk space while receiving data. PWG image dimensions are bounded. These measures limit common malformed-input and resource-exhaustion cases, while a malicious local process still has access to the endpoint.

PDF and raster processing use native libraries inside the ordinary helper process. This process has the same access to files as its Windows account. Use documents from trusted sources and keep the operating system, Python, and rendering libraries current. The packaged DLL is unsigned. The included source and binary checksums support inspection and rebuilding. This project has undergone functional testing and a source review, with broader hardware coverage and independent security review still open.

The installation stores pending and held documents in **%LOCALAPPDATA%\CanonLBP2900\jobs**. Completed document files are removed. The SQLite database retains a recent history of job titles, outcomes, timestamps, and error messages. Held jobs and their diagnostics remain until retried or canceled. The rotating helper log can contain local paths and device errors. Windows also keeps its own spooler records.

A machine-specific printer UUID is derived locally from the host name to preserve the Windows queue identity across setup runs. The public package contains the derivation code. Each installation supplies its own host name and runtime data.

Before sharing diagnostics, review them for document titles, document content, usernames, computer names, paths, and device identifiers. Use a short redacted error message and a synthetic sample document in public issues.

For security reports, use GitHub's **Security → Report a vulnerability** when available. If private reporting has not been enabled, open a minimal issue asking for a private reporting channel. Include sensitive technical details through that private channel.
