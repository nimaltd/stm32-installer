# stm32-installer is now libNIMA

stm32-installer is now part of [libNIMA](https://github.com/nimaltd/libNIMA) installs embedded C libraries into STM32, Zephyr, ESP-IDF, Arduino and PlatformIO projects, from a window or from the `libnima` command, the same on Windows, macOS and Linux. It needs no Python.

Download it from [its releases page](https://github.com/nimaltd/libNIMA/releases/latest), then take this one out:

```bash
pip uninstall stm32-installer
libnima owner/example
```

Every option you used is there: `stm32-installer owner/example --dir Libs/example` is `libnima owner/example --dir Libs/example`.

**Your projects move over by themselves.** An STM32 project stm32-installer installed into moves over the first time libNIMA installs into it or uninstalls from it. Its record, `.stm32-installer.json`, becomes `.libnima.json`, and the lines that mark its blocks in your files name libnima. Each file is saved first, as a `.bak`.

**A library needs a `libnima.yml`** at the root of its repository, as [libNIMA's format page](https://github.com/nimaltd/libNIMA/blob/main/docs/FORMAT.md) shows. The second tab of libNIMA's window writes one with you.

The last release of stm32-installer, 3.0.1, installs nothing. 2.1.0 was the last that installed, and its code stays in this repository's history.

---

## Support

I write these tools and libraries in my own time and give them away, because good tools should be easy to get. If this one saved you an afternoon, there are two things that genuinely help:

**Star [libNIMA](https://github.com/nimaltd/libNIMA).** It costs you one click, it helps other engineers find the tool, and it is the main reason I keep going.

**[Buy me a coffee on Ko-fi](https://ko-fi.com/nimaltd).** Any amount is a real motivation to keep writing, documenting and maintaining this work.

---

## License

Apache License 2.0. See [LICENSE](https://github.com/nimaltd/stm32-installer/blob/main/LICENSE).
