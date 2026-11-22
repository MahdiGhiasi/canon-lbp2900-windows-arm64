# Third-party notices

The application and the Hi-SCoA encoder are distributed under **GPL-3.0-or-later**. The encoder's original copyright and license headers are retained, and the complete source needed to rebuild the included DLL is in **codec/**. The full GPL text is in **COPYING**.

The Windows adaptation was created in November 2026. Changes for the initial public release were made on **2026-11-20**, including loopback request validation, request and queue limits, and an isolated rendering environment.

The CAPT implementation and encoder are based on **captdriver** by Alexey Galakhov and contributors, including contributions by Alexei Gordeev. The source snapshot used was **f7107828725647cf925f9eb0df05c61b6069d49c** of **suluoniu/captdriver-lbp2900**. The Windows USB transport, IPP integration, status monitor, installer, and encoder wrapper are adaptations in this project. Preserve these notices and provide the corresponding source when redistributing the GPL-covered software. [Source snapshot](https://github.com/suluoniu/captdriver-lbp2900/tree/f7107828725647cf925f9eb0df05c61b6069d49c) · [Upstream captdriver](https://github.com/agalakhov/captdriver) · [Maintained fork](https://github.com/mounaiban/captdriver)

**app/ipp_codec.py** comes from **bogdik/mfp-print-scan-server**, revision **23859a71a8838788175120f36e05348488462468**, copyright 2026 Bogdan Shatik. Its MIT license is reproduced in **IPP-codec-LICENSE.txt**. [Source](https://github.com/bogdik/mfp-print-scan-server/tree/23859a71a8838788175120f36e05348488462468)

The page-geometry values in **app/pages.py** reference the captdriver page-parameter documentation. That documentation is attributed to its contributors and published under **CC BY-SA 4.0**. The Windows implementation expresses these measurements as a media table. The applicable license text is included in **licenses/CC-BY-SA-4.0.txt**. [Page measurements](https://github.com/mounaiban/captdriver/wiki/SPECS:-Page-Parameters-Reference-Output-Sizes) · [License](https://creativecommons.org/licenses/by-sa/4.0/)

**Pillow 13.0.0** is provided as its original **cp312 win_arm64** wheel. Its MIT-CMU license and notices for bundled native components are embedded in the wheel's **pillow-13.0.0.dist-info/licenses/LICENSE** file. These notices include the FreeType, JPEG, PNG, zlib, and other component attributions. [Distribution and source](https://pypi.org/project/Pillow/13.0.0/)

**pypdfium2 5.14.0** is provided as its original **win_arm64** wheel, with **PDFium 156.0.8076.0**. Its BSD-3-Clause, Apache-2.0, documentation, PDFium, and native component notices are embedded under **pypdfium2-5.14.0.dist-info/licenses/**. [Distribution and source](https://pypi.org/project/pypdfium2/5.14.0/) · [PDFium binary build](https://github.com/bblanchon/pdfium-binaries/releases/tag/chromium/8076)

**setup/requirements.txt** records the exact rendering packages and their PyPI SHA-256 hashes. **checksums.sha256** covers both wheels and the encoder DLL. The original wheels retain their license files and metadata.

The installer retrieves **Python** from the Python Software Foundation through the WinGet community source and can retrieve **App Installer** from Microsoft's signed releases. These prerequisite installers are downloaded during setup and remain subject to their publishers' terms. [Python license](https://docs.python.org/3/license.html) · [WinGet package source](https://github.com/microsoft/winget-pkgs/tree/master/manifests/p/Python/Python/3/12) · [App Installer releases](https://github.com/microsoft/winget-cli/releases)
