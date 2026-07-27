# evince-synctex

This script wraps [Evince](https://wiki.gnome.org/Apps/Evince) to provide a command-line-friendly SyncTeX integration.
It is based on [Mortal/evince-synctex](https://github.com/Mortal/evince-synctex).

## Installation

A [Python 3](https://www.python.org/downloads) installation is required.

## uv installation

You can install this tool in an isolated environment using [uv](https://docs.astral.sh/uv/getting-started/installation/):

```shell
uv tool install .
```

Run this command from the root of the repository after cloning it.

## System dependencies

This tool requires the following system packages to be installed:

- `dbus-python`
- `libdbus-1-dev`
- `pkg-config`

On Debian/Ubuntu, you can install them with:

```shell
sudo apt install python3-dbus libdbus-1-dev pkg-config
```

## Usage

```shell
evince-synctex PDF_FILE EDITOR_COMMAND
```

This command opens the specified file in Evince and executes the given editor command on a backwards search. A forward search can be performed by using the `-f` flag:

```shell
evince-synctex -f LINE PDF_FILE EDITOR_COMMAND
```
