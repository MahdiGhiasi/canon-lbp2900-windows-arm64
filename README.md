# Canon LBP2900 on Windows ARM64

Print to a USB Canon LBP2900 from ordinary Windows applications on a Windows 11 ARM64 PC.

## Download and install

**[Download the installer ZIP](https://github.com/MahdiGhiasi/canon-lbp2900-windows-arm64/releases/latest/download/Canon-LBP2900-Windows-ARM64.zip)**

1. Download the complete package using the link above. You can also click the green **Code** button on this GitHub page, then **Download ZIP**.
2. Right-click the downloaded ZIP and choose **Extract All**. Open the extracted folder containing **Install.cmd**.
3. Connect the Canon LBP2900 to the PC with a USB cable and turn it on.
4. Double-click **Install.cmd** while signed in as the Windows user who will print.
5. Approve the Windows administrator prompt when it appears. Wait until the installer says **Setup complete**.
6. Open a document, press **Ctrl+P**, and select **Canon LBP2900** as the printer.

No compiler, WSL, or manual Python installation is needed. Setup installs its dependencies automatically; internet access is needed to download any missing prerequisites. Run **Install.cmd** from the extracted folder, not from inside the ZIP.

To uninstall, double-click **Uninstall.cmd** from the same extracted folder and confirm removal. It also deletes local saved print jobs and history.

## How it works

A local helper converts documents from Microsoft's IPP Class Driver to Canon CAPT and sends them through Windows' USB printer interface. This is an independent, community-maintained project. The supplied DLL is built from the included open-source encoder. Canon's proprietary driver is outside this package.

Setup obtains native ARM64 Python 3.12 through WinGet when needed, installs the bundled rendering libraries into a private environment, creates the Windows printer queue, and starts the helper. It can install Microsoft's signed App Installer when WinGet is missing. These downloads require internet access. The helper starts again at sign-in.

The printer defaults to A4, monochrome, 600 dpi, and single-sided output. A5, Letter, Legal, JIS B5, and Executive sizes are advertised. Windows renders copies and page selection before sending the document.

| Compatibility | Status |
| --- | --- |
| Windows 11 ARM64 and USB Canon LBP2900 | Physical printing and power-off/power-on status verified |
| Windows applications using the installed IPP queue | PDF and monochrome PWG Raster input |
| Other printer models, architectures, and Windows versions | Unverified |
| Multiple Windows accounts using the same PC simultaneously | One active helper can own the local printer endpoint |

When the printer is switched off or unplugged, its queue reports Offline. It returns to Ready after USB communication succeeds. Some applications refresh status when their Print dialog is reopened.

Open **Canon LBP2900 Print Status** from Start to see waiting or interrupted jobs. Waiting documents print when the device returns. An interrupted job is held for review. Retrying starts from its first page, which can repeat pages that already printed.

To update, extract a new package and run **Install.cmd** again. Setup restarts an idle helper. A busy helper uses the updated files at the next sign-in, or after another setup run when printing is idle.

If setup reports an error, its window stays open with the reason. The helper log and local job files are under **%LOCALAPPDATA%\CanonLBP2900**. This directory can contain document content, titles, and personal paths. See the privacy and security notes before sharing diagnostics. [Security and privacy](SECURITY.md)

To remove the installation, double-click **Uninstall.cmd** from the extracted package while signed in as the installing user. Confirm removal and approve the administrator prompt when it appears. This removes the Windows queue, helper, shortcuts, private rendering environment, and local history. The confirmation identifies waiting or held documents that will be permanently deleted. Python and WinGet are shared tools with their own uninstall options in Windows settings.

The project is distributed under **GPL-3.0-or-later**. Bundled dependencies retain their individual licenses and attribution. Source, rebuild instructions, and license details are included. [License](COPYING) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Build and verification](BUILDING.md)
