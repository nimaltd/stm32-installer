# stm32-installer

Installs [NimaLTD](https://github.com/nimaltd) embedded C libraries into an STM32 project.

Copying two files into a project is easy. Doing it so the build actually picks them up, without clobbering the settings you changed last month, is the part this handles.

Every command below uses `example` as the library name. Put the real one in its place.

---

## Installing a library

Install the installer once. This needs internet:

```bash
pip install stm32-installer
```

Then, from the root of your STM32 project:

```bash
stm32-installer nimaltd/example
```

To update it later, `pip install --upgrade stm32-installer`. To remove it, `pip uninstall stm32-installer`.

On Windows, if `stm32-installer` is not found after installing, pip put it in a folder that is not on your PATH. `python -m stm32_installer nimaltd/example` runs the same thing.

On Linux or macOS, if pip refuses with `externally-managed-environment`, use `pipx install stm32-installer` instead, and `pipx upgrade stm32-installer` to update.

A library can need a newer installer than the one you have. It then says so and changes nothing:

```
Error: This library needs stm32-installer 1.2.0 or newer, and this one is 1.1.1. Nothing was changed.
Update it with:
    pip install --upgrade stm32-installer
```

### Without internet

On a machine that has internet, save the installer as a file:

```bash
pip download stm32-installer
```

That saves one file, such as `stm32_installer-1.1.2-py3-none-any.whl`, where the number is the installer's version. Download the library too, from the green **Code** button, **Download ZIP**. Copy both to the machine that has no internet, then from your project:

```bash
pip install stm32_installer-1.1.2-py3-none-any.whl
stm32-installer D:/Downloads/example-master.zip
```

Neither line needs the internet. The installer needs nothing but itself, and the library comes from the zip.

### What to install

The one argument can be any of these:

| You have | You type |
|---|---|
| Nothing yet, and internet | `stm32-installer nimaltd/example` |
| The library's GitHub address | `stm32-installer https://github.com/nimaltd/example` |
| The zip from GitHub's **Download ZIP** | `stm32-installer D:/Downloads/example-master.zip` |
| That zip unpacked, anywhere on disk | `stm32-installer D:/Downloads/example-master` |
| The library's folder, already inside your project | `stm32-installer example` |

A bare name like `example` means `nimaltd/example` on GitHub, unless a folder of that name exists where you run it, in which case the folder is used. A path that does not exist is reported as missing rather than looked up on GitHub, so a typo in `D:/Downloads/...` gets a straight answer.

The zip does not need unpacking first. If you did unpack it with Windows' **Extract All**, which puts `example-master` inside another `example-master`, either folder works.

### Options

| Option | What it does |
|---|---|
| `--ref v2.0.0` | A tag, a branch or a commit to take from GitHub. `master` when not given |
| `--dir Libs/example` | The folder of your project to install into. Asked for when not given, with the library's name as the answer if you just press Enter |
| `--project D:/Work/MyBoard` | Your project's root, when you are not running from it |
| `--ide cubeide` | Register with this IDE only: `cmake`, `cubeide`, `keil` or `iar`. Every one found, when not given |
| `--version` | Show which version of the installer you have, and do nothing else |

`--ref` holds a project on one release, which is useful when you need exactly what you built with last time:

```bash
stm32-installer nimaltd/example --ref v2.0.0         # a tag
stm32-installer nimaltd/example --ref develop        # a branch
stm32-installer nimaltd/example --ref 00949e695e16   # an exact commit
```

### Where the files go

**From GitHub, from a zip, or from a folder outside your project**, the files the library's `library.yml` lists are copied into a folder of your project. Nothing else comes with them, so the library's tests never reach your build. The zip or folder you gave is left exactly as it was.

**A folder already inside your project** becomes the library where it stands. The header and source move to its top, your config file is created, and everything that belongs to the repository rather than your firmware is removed from it, the test folder above all. `--dir` does not apply here, since the folder is already where it is going. Rename it first if you want it called something else.

### The folder question

Without `--dir`, you are asked where the library should go:

```
Folder to install into [example]:
```

Press Enter for the default. In a script or on a build server, where nobody is there to answer, the default is taken without asking, rather than waiting for ever.

### Updating a library

Run the same command again. The code is replaced, and your `example_config.h` is kept, because it is yours:

```
Files
  written example/example.h
  written example/example.c
  kept    example/example_config.h  not overwritten

This was an update. Code replaced, your configuration kept.
```

### What you see

A first install from a downloaded zip, into a CubeMX project that builds with both CMake and STM32CubeIDE:

```
Reading example-master.zip ...

example 2.0.0
What this library does, in one line
middleware / system

Files
  written example/example.h
  written example/example.c
  written example/LICENSE.md
  written example/NOTICE
  written example/README.md
  created example/example_config.h  yours to edit

Project
  updated CMake  Added example to CMakeLists.txt, linked to ${CMAKE_PROJECT_NAME}.
          backup: CMakeLists.txt.20260923-193649.bak
  updated STM32CubeIDE  Added example to the include path and source folders in .cproject.
          Refresh the project in CubeIDE (F5) so it picks up the new files.
          backup: .cproject.20260923-193649.bak

Done. #include "example.h" and you are away.
```

The first line says where the library came from: `Fetching nimaltd/example ...` from GitHub, `Reading ...` from a zip or a folder.

---

## What it does for you

**Finds your IDE and wires the library in.** CMake, STM32CubeIDE, Keil MDK and IAR are all handled, and a project can be more than one of them at once.

| IDE | What gets changed |
|---|---|
| CMake | The library gets its own `CMakeLists.txt`, and two lines are appended to yours |
| STM32CubeIDE | The include path, and the source folders where the project lists them, in every build configuration of `.cproject` |
| Keil MDK 5 and 6 | A file group and the include path in `.uvprojx` |
| IAR EWARM | A file group and the include path in `.ewp` |

**Never overwrites your configuration.** `example_config.h` is created once. Reinstall as often as you like: the code is replaced, your settings are not.

**Leaves the file looking like you wrote it.** An added line copies the indentation, the line ending and the path separator of the lines around it. These files go into version control, so a correct edit that shows up as a whole file diff is still a bad edit.

**Keeps your CMakeLists.txt short.** Your project gets two lines that never change, and the library's file list lives with the library:

```cmake
# >>> stm32-installer: example >>>
add_subdirectory(example)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE example_lib)
# <<< stm32-installer: example <<<
```

The target is called `example_lib` rather than `example`, because a project is often named after the library being tried out in it and CMake allows only one target per name. The `PRIVATE` keyword is dropped when your project links its libraries without one, since CMake refuses to mix the two forms.

The generated `example/CMakeLists.txt` declares an INTERFACE target, not a STATIC one. That matters: an INTERFACE target hands its sources to whoever links it, so they are compiled as part of your application and inherit its defines and include paths. That is what lets a driver's `.c` file find `main.h` and the HAL headers. A STATIC library would not see them and would fail to compile.

**Backs up before editing.** Every project file is copied to a timestamped `.bak` first. If the file is not one it recognises, it changes nothing and prints what to click instead.

**Edits the project, not a copy of it.** IAR leaves a `Backup of <name>.ewp` beside the real project when it upgrades one, and that copy is a valid project file whose name sorts first. The workspace file is asked which project is the real one, and backups are skipped.

**Keeps the repository out of your build.** CubeIDE compiles every `.c` under your project, and a library repository ships a test suite with its own `main()`. Left in place, that breaks your build with an error that points nowhere useful. So only the listed files are copied, and a repository that sits inside your project has everything else removed from it.

**Tells you what the library needs.** It reads your `stm32xxxx_hal_conf.h` and `.ioc` and warns before you hit a confusing compile error:

```
Requirements
  check   HAL SPI module is not enabled
          Uncomment HAL_SPI_MODULE_ENABLED in stm32f4xx_hal_conf.h
  ok      GPIO is configured
  check   This library needs an RTOS and none was found
          It expects freertos. Enable it in CubeMX under Middleware.
```

It cannot switch a peripheral on for you. The `.ioc` belongs to CubeMX, and editing it behind CubeMX's back goes wrong quietly.

---

## For someone writing a library

Put a `library.yml` at the root of the repository.

```yaml
name: example
description: What this library does, in one line
repository: https://github.com/nimaltd/example
license: Apache-2.0

kind: middleware        # driver, middleware, rtos, protocol, filesystem, utility, bsp
category: system        # sensor, storage, display, communication, wireless,
                        # rtos, timing, power, input, math, system

provides: []            # what this gives other libraries. An RTOS says [rtos]

requires:
  installer: 1.1.0      # the oldest stm32-installer that reads this file
  libraries: []         # other NimaLTD libraries, by name
  hal: true
  cmsis: true
  rtos: none            # none, optional, any, freertos, cmsis-os2, threadx
  hal_modules: [spi]    # must be enabled in stm32xxxx_hal_conf.h
  peripherals:
    - type: spi
      count: 1
      note: Master mode, 8 bit
  c_standard: c11

install:
  layout: flat          # flat (default) puts every file at the top of the
                        # folder, so one include path covers the library.
                        # mirror keeps the repository's own folders, for a
                        # library too big to flatten sensibly.

files:
  headers:
    - src/example.h           # listed first: the one "#include" is printed for
    - src/port/*.h            # a wildcard, matched the way a shell would
  sources:
    - src/example.c
    - from: src/port/spi.c    # a file can say exactly where it goes, which
      to: port/spi.c          # overrides the layout for that one file

once:                   # copied once, then it belongs to the user
  - from: src/example_config.h
  - from: src/example_port.c  # a .c starter works the same way
    to: my_port.c             # "to" only when the name should change

extras:                 # copied as they are, no compiling
  - LICENSE.md          # LICENSE.md and NOTICE are the default, so this
  - NOTICE              # section can be left out entirely
  - README.md
  - docs                # a folder, copied whole and keeping its shape
```

There is no `version` in it. The installer reads the version from the `@version` tag in the file comment of the first header listed, so it is written in the code and nowhere else:

```c
/**
 * @file        example.h
 * @version     2.0.0
 */
```

`requires.installer` is the oldest stm32-installer that reads the file correctly. It is checked before anything else in the file is read, so when a manifest starts using something only a newer installer understands, raising this makes an older one stop with a message saying to update, rather than read the file wrongly without a word. Write it as three numbers, `1.1.0`: unquoted, YAML reads `1.10` as the decimal number `1.1`, and that is refused.

A file listed under `once` is copied only when it is missing, so the user's own edits survive every update. It keeps its own name unless you give it a `to`.

The key says what happens rather than what the file is. It is usually a configuration header, but the same rule fits a port layer someone fills in, or a table they tune: anything that is the library's to start and theirs from then on.

One catch worth knowing: `#include "x.h"` searches the including file's own folder before any include path, so a config sitting beside the header that includes it will always win. That is fine when the library's tests use the same config, and it is why the tests in these libraries are written against `EXAMPLE_MAX_TASKS` rather than a fixed number.

The include path follows the layout on its own: `flat` gives the library folder, `mirror` gives wherever the headers landed. Add `install.include_dirs` only when that guess is wrong.

Three things about this that are easy to get wrong:

**A `.c` template is a source.** If you ship a port layer as `src/example_port.c` that lands as `my_port.c`, it is added to the build like any other source. Leaving it out would fail at link time with undefined references and no clue why.

**`kind: rtos` implies `provides: [rtos]`.** A library that is an operating system satisfies another library's RTOS requirement, whether or not you remembered to write it down.

**`LICENSE.md` and `NOTICE` travel with the code.** The Apache licence requires it, and the NOTICE file is what carries your attribution into someone else's product. They are never removed during cleanup.

That is everything the repository needs. There is no installer script to copy in: put the install lines from the top of this page in your README, with your library's name in them.

---

## Running the tests

```bash
python test/run_tests.py
```

---

## Support

I write these tools and libraries in my own time and give them away, because good tools should be easy to get. If this one saved you an afternoon, there are two things that genuinely help:

**Star the repo.** It costs you one click, it helps other engineers find the tool, and it is the main reason I keep going.

**[Buy me a coffee on Ko-fi](https://ko-fi.com/nimaltd).** Any amount is a real motivation to keep writing, documenting and maintaining this work.

[![GitHub](https://img.shields.io/badge/GitHub-Follow-black?style=for-the-badge&logo=github)](https://github.com/NimaLTD)
[![YouTube](https://img.shields.io/badge/YouTube-Subscribe-red?style=for-the-badge&logo=youtube)](https://youtube.com/@nimaltd)
[![Instagram](https://img.shields.io/badge/Instagram-Follow-purple?style=for-the-badge&logo=instagram)](https://instagram.com/github.nimaltd)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue?style=for-the-badge&logo=linkedin)](https://linkedin.com/in/nimaltd)
[![Email](https://img.shields.io/badge/Email-Contact-red?style=for-the-badge&logo=gmail)](mailto:nima.askari@gmail.com)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-orange?style=for-the-badge&logo=ko-fi)](https://ko-fi.com/nimaltd)

---

## License

Apache License 2.0. See [LICENSE](https://github.com/nimaltd/stm32-installer/blob/main/LICENSE).
