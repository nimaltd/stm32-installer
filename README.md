# stm32-installer is now lib-installer

stm32-installer, together with the four installers beside it, is one installer now: [lib-installer](https://github.com/nimaltd/lib-installer). It installs embedded C libraries into STM32, Zephyr, ESP-IDF, Arduino and PlatformIO projects, with the commands stm32-installer had.

```bash
pip uninstall stm32-installer
pip install lib-installer
lib-installer owner/example
```

Every option you used is there: `stm32-installer owner/example --dir Libs/example` is `lib-installer owner/example --dir Libs/example`.

**Your projects move over by themselves.** An STM32 project stm32-installer installed into moves over the first time lib-installer installs into it or uninstalls from it. Its record, `.stm32-installer.json`, becomes `.lib-installer.json`, and the lines that mark its blocks in your files name lib-installer. Each file is saved first, as a `.bak`.

**Your libraries install as they did.** lib-installer reads every key of an `installer.yml` written for stm32-installer, `requires.stm32_installer` among them. A library written for lib-installer 3.0.0 names its platform under `platform`, as [its README](https://github.com/nimaltd/lib-installer#for-someone-writing-a-library) shows.

This last release, 3.0.0, only says this, and installs nothing. 2.1.0 was the last that installed, and its code stays in this repository's history.

---

## Support

I write these tools and libraries in my own time and give them away, because good tools should be easy to get. If this one saved you an afternoon, there are two things that genuinely help:

**Star [lib-installer](https://github.com/nimaltd/lib-installer).** It costs you one click, it helps other engineers find the tool, and it is the main reason I keep going.

**[Buy me a coffee on Ko-fi](https://ko-fi.com/nimaltd).** Any amount is a real motivation to keep writing, documenting and maintaining this work.

---

## License

Apache License 2.0. See [LICENSE](https://github.com/nimaltd/stm32-installer/blob/main/LICENSE).
