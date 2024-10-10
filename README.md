# Seestar_Alp

There are many things in this repository to allow you to interact with your Seestar in interesting ways.

`./device` directory has the code for the actual seestar control program. It accepts and returns JSON strings

`./bruno`  This directory has the API to the Seestar in an easy to ues format for the Bruno program or any other program that can send http requests.

`./docker` This directory has instruction and code to create a docker container that has all the things needed to run the GUI and the device control code

`./front` This directory has the code to render the Web GUI.  It is named SSC for Simple Seestar Controler. It makes communicating with the Seestar easy.

`./raspberry_pi` Here you will find instructions and code to allow you to use a raspberry Pi to host the GUI and the device control software.  If you know RPi this make it very easy to build a standalone device.  You won't have to install any other softwhere just communicate with it with your browser. Look at the README.md in the directory for more info.

`./templates` This directory contains device driver templates for building a new part of an alpaca driver. It is Python code, you probably won't need this unless you are a very advanced user.

`./thunder-test` is the start of unit testing of the code with the Thunder product

Along the right side of the page you will see the release information. When you look in a release you will see the source code for the release as well as zips for single directory installation of the project.


### Where do I start?

That depends on your goals. (of course)

If you want to get in and learn the code and see how it all works then you can clone this git repository or download the code from the release, or from the main branch.  You will be interested in the ./device and ./front directories at first. 

If you just want to use the GUI and commnicate with your Seestar then the standalone install may be right for you. The standalone install is described below.

## Installation

### Standalone package

#### Windows/Linux
The easiest way to install and run on Windows is to download a zip file that will allow you to run from one .exe file and everything will come up. If you want to run from source code then you will need to follow the Mac/Source install below.

Download win_seestar_alp.zip or linux_seestar_alp.zip from the lastest release at [this github location](https://github.com/smart-underworld/seestar_alp/releases)

Releases will be named with the version of the seestar code. Eg:

`v2.1.1`

or

`v2.1.1-51-gdb0d6cc`

NOTE that the simpler of the two, without the `-51-gdb0d6cc` is an official release, and the other one is a build done in-between official releases. Know that these may not be as stable.

Unzip the file and put the enclosed folder anywhere you would like.
Open a command window and navigate the the foler that contains seestar_alp.exe
Now execute seestar.exe, you should see the message "Startup Complete" when everything is ready to go.
If the Seestar is not turned on you will see messages in this command windows.

The web interface should be available in your browser at <http://localhost:5432/>.

If you need to modify the config.toml file it is located in the _internal subdirectory.
Log files named alpaca.log will be written to the same directory as the executable
Ctrl-c will close the windows when you are finished

##### Updating from prior version (Windows/Linux)
Rename the directory that you are currently using for the code and download and install the new version.  This give you a way to revert to the old version if there is an issue.  You will need to make any changes to your config.toml in the new version.

### Source code

#### Ensure development tools are installed

-  ##### Mac

    Because of code signing issues the Mac can't use the one folder solution described for windows/linux, instead you will need to run from source code.

    ##### Ensure xcode command line tools are installed:
    ```
    xcode-select -p
    ```
    If the above prints an error, rather than an install path - you need to install `XCode command line tools` via:
    ```
    xcode-select --install
    ```
    This will ensure the apps like `git` and `python3` are installed.
    ##### Check python version
    You need version 3.12 or greater of python
    ```
    python --version
    ```

    ##### Create an alias from `python3` to `python` (optional)

    This tutorial references the `python` executable, rather than `python3`. To avoid confusion, you can create an alias (and equivalent `pip` alias):
    ```
    echo "alias python='python3'" >> ~/.zprofile
    echo "alias pip='pip3'" >> ~/.zprofile
    ```

- ##### Windows
    - Install Python on your system. (Get version 3.12 or above)    <https://www.python.org/downloads/>
        If you already have python installed verify that it is version 3.12 or above
        ```
        python --version
        ```

    - Download and install the following:
        <https://visualstudio.microsoft.com/visual-cpp-build-tools/>


#### Get the seestar_alp code, and install requirements

You have the choice of running from a versioned, point-in-time release of the code, or to use the latest source in `git`

- Zip file release
    Download the source file zip from the current relelase at:

    <https://github.com/smart-underworld/seestar_alp/releases>

    Unzip the file and put the resultant directory wherever you want it.

- Latest source:

    ```
    git clone https://github.com/smart-underworld/seestar_alp
    ```

Load the project dependencies by issuing the following in the directory where you unpacked the code
```
    pip3 install -r requirements.txt
```

Now you are ready to run.  In the directory where you unpacked the code enter

```
python root_app.py
```
You should see the message "Startup Complete" when everything is ready to go.

The web interface should be available in your browser at <http://localhost:5432/>.

You can configure the list of Seestars you will be controlling by updating the last portion of the config file 
device/config.toml. You can add as many Seestars as you like.

If you want to directly interact with the Alpaca interface to the Seestar you can use Bruno to send commands.

Download and install the Bruno program from <https://www.usebruno.com>

From the Collections menu item in Bruno, select the 'Seestar Alpaca API' 

Use Bruno to test out control of your seestar using the "GettingStarted" section
Be sure to set your environment to target your specfic Seestar.

#### Updating from prior version (Mac/Source Code)
Rename the directory that you are currently using for the code and download and install the new version.  This give you a way to revert to the old version if there is an issue.  You will need to make any changes to your config.toml in the new version.

### Raspberry Pi
Follow the instructions in the readme.md file in the raspberry_pi directory

## How to get Support

I will set priority on responding from my Github and my Discord Channel:

Public Discord Channel for up to date info
<https://discord.gg/B3zDCAMP4V>

Facebook Group: Smart Telescope Underworld
<https://www.facebook.com/groups/373417055173095/>

YouTube Channel
<https://www.youtube.com/channel/UCASdbiZUKFGf6VR4H_mijxA>

Github
<https://github.com/smart-underworld>



## Current code

- This version provides a unified web and device interface. You don't have to run two differnt programs, just one. 
- The web interface has been significantly enhanced to now allow you to send commands as well as see and set many of the configuration parameters that are used by the Seestar.
- The schedule page has been improved and now allows you to Clear the schedule, save and load schedules
- this may be removed   You can display your local sun rise/sun set times
- It now gives visual feedback as to where in the schedule it is currently executing.
- Schedule creation can be done when not connected to the Seestar
- There are many many ways you can enter the RA/DEC of a desired target on the Image and Mosaic pages or when you want to schedule an image or mosaic:
    1. Enter the name of the target in the image name field and press the search icon and the RA/DEC will be retreived from Simbad. It will also flag the data as J2000, and turn on the LP filter if the object is an HII region, Emission Nebula, Planetary Nebula or a Supernova Remnant.
    2.  If you have Stallarium configued to allow communcation from outside sources with the remote plugin, you can select an object in Stellarium and on the SSC page press the star icon and it will retreive the RA/DEC, check the J2000 box, and check the LP Filter box if the object is of type HII region, Emission Nebula, Planetary Nebula or a Supernova Remnant.
    3. You can copy and paste the RA/DEC from many other websites.
        a. Telescopious
        b. Astro mosaic,
        c. Telescopious from csv file
        d. Mosaic Planner
        e. Astro-bin
        f. Cartes du Ciel



## Version 2.0, October 2024
added Simple Seestar (web) Client
added Federation support to control multiple Seestars as one

## Version 1.1.0b1, June 29, 2024 (experimental)

This project, based on AlpacaDevice, is a lightweight Python framework to control and automate all aspect of Seestar S50.
It implements and extends the Alpaca protocol and ASCOM Standards


