# AlpycaDevice - Python Alpaca Device Driver SDK

## Version 0.50, November 28, 2023 (experimental)

<img align="right" width="210" height="166" hspace="20" vspace="20" src="https://ascom-standards.org/alpyca/readme-assets/AlpacaLogo210.png">

This project is a lightweight Python framework for a device
driver that supports the Alpaca protocol and ASCOM Standards. It implements
a basic Rotator device with a simple simulation for Conform tests.
**Templates for all ASCOM device types are provided**. The "boiler plate" logic
remains the same for any device.

## [AlpycaDevice SDK 0.5.0 Documentation](https://ascom-standards.org/alpycadevice/)

[![AlpycaDevice Video](https://raw.githubusercontent.com/BobDenny/AlpycaDevice/master/docs/source/vthumb.png)](https://www.youtube.com/watch?v=soGb0j4iOt4 "AlpycaDevice Video")

## Quick Start

Open the [Alpyca Device Quick Start section of the above
documentation](https://ascom-standards.org/alpycadevice/quickstart.html). This gives
instructions on getting the sample to run and pass the ConformU checks (see below),
as well as step-by-step detailed instructions on creating a skeleton Alpaca
driver for any ASCOM device using the provided templates.

## Status of this project

One more experimental release. A few problems were detected after 0.4 thanks
to user @jhannon.

**Templates for all ASCOM
device types are included**. While preserving simplicity
as much as possible, version 0.5.0 can easily be configured for multiple ASCOM
device types and multiple instances of a given ASCOM device type within the
Alpaca device/server. The sample Rotator simulator passes [Conform
Universal](https://github.com/ASCOMInitiative/ConformU#conform-universal) for
Rotator device, as well as [Conform
Universal](https://github.com/ASCOMInitiative/ConformU#conform-universal) Alpaca
Protocol tests. The 0.4.0 Conform logs are part of the repository. No changes
to 0.5.0 that would affect the Rotator simulator, only changes to the templates.

## Potential Applications

* **Self-contained** device (e.g. on Raspberry Pi etc) that can be used by native Alpaca
  speaking programs like [Cartes du Ciel](https://www.ap-i.net/skychart/en/start),
  [Sky Safari 7](https://skysafariastronomy.com/) (pro or plus),
  as well as Windows apps like
  [SGP](https://www.sequencegeneratorpro.com/),
  [NINA](https://nighttime-imaging.eu/),
  [ACP](https://acpx.dc3.com/), etc. that speak Windows ASCOM/COM
* Linux/Max/Windows driver for Windows apps like
  [SGP](https://www.sequencegeneratorpro.com/),
  [NINA](https://nighttime-imaging.eu/),
  [ACP](https://acpx.dc3.com/), etc. that
  speak Windows ASCOM/COM
* Linux/Mac/Windows driver for native Alpaca-speaking apps like
  [Sky Safari 7](https://skysafariastronomy.com/).
* Use this to make an Alpaca front end for an INDI device running on Linux or MacOS,
  and make that device usable from Windows programs as noted above.
* Use your imagination...

## How to get Support

Use the [ASCOM Driver and Application Development Support Forum](https://ascomtalk.groups.io/g/Developer).
