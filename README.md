# stm32-installer

Installs [NimaLTD](https://github.com/nimaltd) embedded C libraries into an STM32 project.

Copying two files into a project is easy. Doing it so the build actually picks them up, without clobbering the settings you changed last month, is the part this handles.

---

## For someone using a library

Run either of these from the root of your STM32 project.

**You downloaded the repository into your project already:**

```bash
python fsm/install.py
```

Nothing is asked, and nothing is installed on your machine. The installer is fetched into a temporary folder, used, and deleted, so there is no pip step, no packages, and no stale copy to go out of date. Plain Python is all you need.

The repository folder becomes the library folder: the header and source move to the top, your config file is created, and everything that belongs to the repository rather than your firmware is removed.

**You have not downloaded anything:**

```bash
pip install https://github.com/nimaltd/stm32-installer/archive/refs/heads/main.zip
stm32-install fsm
```

You are asked which folder to use. Only the files the library actually needs are downloaded, not the whole repository.

The first line is needed once, not once per library. Run it again whenever you want the newest installer.

Either way it then registers the library with your IDE, and prints what it needs from your CubeMX setup.

---

## What it does for you

**Finds your IDE and wires the library in.** CMake, STM32CubeIDE, Keil MDK and IAR are all handled, and a project can be more than one of them at once.

| IDE | What gets changed |
|---|---|
| CMake | The library gets its own `CMakeLists.txt`, and two lines are appended to yours |
| STM32CubeIDE | The include path, in every build configuration in `.cproject` |
| Keil MDK 5 and 6 | A file group and the include path in `.uvprojx` |
| IAR EWARM | A file group and the include path in `.ewp` |

**Never overwrites your configuration.** `fsm_config.h` is created once. Reinstall as often as you like: the code is replaced, your settings are not.

**Keeps your CMakeLists.txt short.** Your project gets two lines that never change, and the library's file list lives with the library:

```cmake
# >>> stm32-installer: fsm >>>
add_subdirectory(fsm)
target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE fsm)
# <<< stm32-installer: fsm <<<
```

The generated `fsm/CMakeLists.txt` declares an INTERFACE target, not a STATIC one. That matters: an INTERFACE target hands its sources to whoever links it, so they are compiled as part of your application and inherit its defines and include paths. That is what lets a driver's `.c` file find `main.h` and the HAL headers. A STATIC library would not see them and would fail to compile.

**Backs up before editing.** Every project file is copied to a timestamped `.bak` first. If the file is not one it recognises, it changes nothing and prints what to click instead.

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
name: fsm
version: 2.0.0
description: Finite state machine and task queue for STM32
repository: https://github.com/nimaltd/fsm
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
                        # mirror keeps inc/ and src/, for a library too big
                        # to flatten sensibly.

files:
  headers:
    - inc/fsm.h
  sources:
    - src/fsm.c
    - from: src/port/spi.c    # a file can say exactly where it goes, which
      to: port/spi.c          # overrides the layout for that one file

config:                 # copied once, then it belongs to the user
  - from: template/fsm_config.h
  - from: template/fsm_port.c       # a .c template works the same way
    to: my_port.c                   # "to" only when you want a different name

extras: [LICENSE.md, NOTICE]   # this is the default, so it can be left out
```

Templates live in `template/`, under the name they should end up with. That folder is stripped out after an install, so the copy the user edits is the only one left.

The include path follows the layout on its own: `flat` gives the library folder, `mirror` gives wherever the headers landed. Add `install.include_dirs` only when that guess is wrong.

Three things about this that are easy to get wrong:

**A `.c` template is a source.** If you ship a port layer as `template/demo_port.c`, it is added to the build like any other source. Leaving it out would fail at link time with undefined references and no clue why.

**`kind: rtos` implies `provides: [rtos]`.** A library that is an operating system satisfies another library's RTOS requirement, whether or not you remembered to write it down.

**`LICENSE.md` and `NOTICE` travel with the code.** The Apache licence requires it, and the NOTICE file is what carries your attribution into someone else's product. They are never removed during cleanup.

Then copy `install.py` in from any library that already has it. Nothing in it needs changing: it works out the library from the folder it sits in.

---

## Running the tests

```bash
python test/run_tests.py
```

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
