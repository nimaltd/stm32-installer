# stm32-installer

Installs [NimaLTD](https://github.com/nimaltd) embedded C libraries into an STM32 project.

Copying two files into a project is easy. Doing it so the build actually picks them up, without clobbering the settings you changed last month, is the part this handles.

Every command below uses `example` as the library name. Put the real one in its place.

---

## For someone using a library

Run either of these from the root of your STM32 project.

**You downloaded the repository into your project already:**

```bash
python example/install.py
```

Nothing is asked, and nothing is installed on your machine. The installer is fetched into a temporary folder, used, and deleted, so there are no packages and no stale copy to go out of date. Plain Python is all you need.

The repository folder becomes the library folder: the header and source move to the top, your config file is created, and everything that belongs to the repository rather than your firmware is removed.

**You have not downloaded anything:**

Take `install.py` from the library you want. It knows which library it belongs to, so there is nothing else to say.

**Windows, Command Prompt:**

```bat
curl -fsSL https://raw.githubusercontent.com/nimaltd/example/master/install.py -o install.py && python install.py
```

**Windows, PowerShell:**

```powershell
irm https://raw.githubusercontent.com/nimaltd/example/master/install.py -OutFile install.py; python install.py
```

PowerShell needs `irm` rather than `curl`, because `curl` there is an alias for a different command that does not understand those options.

**Linux and macOS:**

```bash
curl -fsSL https://raw.githubusercontent.com/nimaltd/example/master/install.py -o install.py && python3 install.py
```

You are asked which folder to use. Only the files the library actually needs are downloaded, not the whole repository. Afterwards `install.py` deletes itself, so nothing is left lying in your project.

It stays if you gave it a library name, since then you are using it as a tool and probably have another one to install: `python install.py nimaltd/example`. It also stays if the install failed, so you can try again.

**Pinning a version.** By default you get the newest code on the library's default branch. Add `--ref` to hold a project on one release:

```bash
python install.py --ref 2.0.0              # a tag
python install.py --ref develop            # a branch
python install.py --ref 00949e695e16       # an exact commit
```

It then registers the library with your IDE, and prints what it needs from your CubeMX setup.

---

## What it does for you

**Finds your IDE and wires the library in.** CMake, STM32CubeIDE, Keil MDK and IAR are all handled, and a project can be more than one of them at once.

| IDE | What gets changed |
|---|---|
| CMake | The library gets its own `CMakeLists.txt`, and two lines are appended to yours |
| STM32CubeIDE | The include path, in every build configuration in `.cproject` |
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

**Strips the repository scaffolding.** CubeIDE compiles every `.c` under your project, and a library repository ships a test suite with its own `main()`. Left in place, that breaks your build with an error that points nowhere useful.

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
version: 2.0.0
description: What this library does, in one line
repository: https://github.com/nimaltd/example
license: Apache-2.0

kind: middleware        # driver, middleware, rtos, protocol, filesystem, utility, bsp
category: system        # sensor, storage, display, communication, wireless,
                        # rtos, timing, power, input, math, system

provides: []            # what this gives other libraries. An RTOS says [rtos]

requires:
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
    - src/example.h
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

A file listed under `once` is copied only when it is missing, so the user's own edits survive every update. It keeps its own name unless you give it a `to`.

The key says what happens rather than what the file is. It is usually a configuration header, but the same rule fits a port layer someone fills in, or a table they tune: anything that is the library's to start and theirs from then on.

One catch worth knowing: `#include "x.h"` searches the including file's own folder before any include path, so a config sitting beside the header that includes it will always win. That is fine when the library's tests use the same config, and it is why the tests in these libraries are written against `EXAMPLE_MAX_TASKS` rather than a fixed number.

The include path follows the layout on its own: `flat` gives the library folder, `mirror` gives wherever the headers landed. Add `install.include_dirs` only when that guess is wrong.

Three things about this that are easy to get wrong:

**A `.c` template is a source.** If you ship a port layer as `src/example_port.c` that lands as `my_port.c`, it is added to the build like any other source. Leaving it out would fail at link time with undefined references and no clue why.

**`kind: rtos` implies `provides: [rtos]`.** A library that is an operating system satisfies another library's RTOS requirement, whether or not you remembered to write it down.

**`LICENSE.md` and `NOTICE` travel with the code.** The Apache licence requires it, and the NOTICE file is what carries your attribution into someone else's product. They are never removed during cleanup.

Then copy `install.py` in from this repository and set the three constants near the top:

```python
LIBRARY = "nimaltd/example"  # owner/name, so a fork under another account works
BRANCH  = "master"           # the branch that library lives on

# Where the installer itself comes from.
SOURCE = "https://github.com/nimaltd/stm32-installer/archive/refs/heads/main.zip"
```

`LIBRARY` also accepts a full GitHub URL. It is what makes the one line install work: the file knows which library it belongs to, so whoever downloads it has nothing to type.

That is all three of them. If you maintain your own libraries with this tool, point `SOURCE` at your own fork and the rest follows.

---

## Running the tests

```bash
python test/run_tests.py
```

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
