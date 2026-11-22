# Building and verifying

The repository contains the complete installer, Python source, ARM64 encoder DLL, C encoder source, and original ARM64 rendering wheels. A repository ZIP can be extracted and installed directly.

To rebuild the native DLL, install **Zig 0.15.2** and run this command from the repository root with Python 3.

~~~text
python scripts/build_codec.py
~~~

Use **--zig** to provide the path to the Zig executable. Use **--output** to build to a separate file. The script targets **aarch64-windows-gnu**, optimizes with **-O2**, strips debug information, and compiles the three source files listed in the script. Zig can cross-compile this DLL on Windows, Linux, or WSL. [Zig download](https://ziglang.org/download/)

The rendering wheels can be downloaded again with the following command. Pip verifies the hashes in the requirements file.

~~~text
python -m pip download --only-binary=:all: --no-deps --require-hashes --platform win_arm64 --python-version 3.12 --implementation cp --abi cp312 --dest setup/wheels -r setup/requirements.txt
~~~

Run the source and protocol checks with Python 3.12 or newer.

~~~text
python -B scripts/verify_release.py
python -B -m unittest discover -s tests -v
~~~

The tests use temporary directories, a separate loopback server, and synthetic document bytes. They exercise IPP requests, offline status, malformed requests, browser rejection, input-size limits, and queue limits. They leave the installed printer queue and USB device outside the test environment. Physical printing requires Windows ARM64 and the printer.

On Windows, the suite also exercises uninstall using temporary application folders and shortcuts, with mocked printer and process operations. The NTFS junction case runs where the test environment permits creating junctions. GitHub CI includes a Windows job for these checks.

Build a distributable ZIP with the following command.

~~~text
python -B scripts/package_release.py
~~~

The output is **dist/Canon-LBP2900-Windows-ARM64.zip**. Packaging verifies the recorded binary hashes and selects files from an explicit manifest, so local documents, spool data, Git metadata, logs, and development environments are excluded. ZIP entries use a fixed timestamp. Update the manifest when intentionally adding release files.

When updating dependencies or rebuilding the DLL, review the upstream sources and license notices, update **checksums.sha256**, and rerun the checks. Review the included **SOURCES.txt** for the original upstream references.
