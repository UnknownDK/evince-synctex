#!/usr/bin/env python3

# Copyright (C) 2010 Jose Aliste <jose.aliste@gmail.com>
#               2011 Benjamin Kellermann <Benjamin.Kellermann@tu-dresden.de>
#               2018 Mathias Rav <m@git.strova.dk>
#               2019 Eric Förster <efoerster@users.noreply.github.com>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public Licence as published by the Free Software
# Foundation; either version 2 of the Licence, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public Licence for more
# details.
#
# You should have received a copy of the GNU General Public Licence along with
# this program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA  02110-1301, USA

"""Provides a command-line-friendly SyncTeX integration for Evince."""

import argparse
import logging
import os
import re
import shlex
import subprocess
import urllib.parse

import dbus

RUNNING, CLOSED = range(2)

# Evince 49 renamed its D-Bus namespace from "org.gnome.evince" to
# "org.gnome.Evince". Both releases derive every name/path/interface from that
# namespace using the same pattern, so we detect which one is available at
# runtime and configure the constants below accordingly.
EV_NAMESPACE_NEW = "org.gnome.Evince"
EV_NAMESPACE_OLD = "org.gnome.evince"


def _configure_dbus_names(bus):
    global EV_DAEMON_PATH, EV_DAEMON_NAME, EV_DAEMON_IFACE
    global EVINCE_PATH, EVINCE_IFACE, EV_WINDOW_IFACE, EV_WINDOW_PATH

    namespace = _detect_namespace(bus)
    base_path = "/" + namespace.replace(".", "/")

    EV_DAEMON_PATH = base_path + "/Daemon"
    EV_DAEMON_NAME = namespace + ".Daemon"
    EV_DAEMON_IFACE = namespace + ".Daemon"

    EVINCE_PATH = base_path + "/Evince"
    EVINCE_IFACE = namespace + ".Application"

    EV_WINDOW_IFACE = namespace + ".Window"
    EV_WINDOW_PATH = base_path + "/Window/0"


def _detect_namespace(bus):
    dbus_obj = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
    dbus_iface = dbus.Interface(dbus_obj, "org.freedesktop.DBus")
    names = set(dbus_iface.ListNames()) | set(dbus_iface.ListActivatableNames())
    if EV_NAMESPACE_OLD + ".Daemon" in names and EV_NAMESPACE_NEW + ".Daemon" not in names:
        return EV_NAMESPACE_OLD
    return EV_NAMESPACE_NEW


# Default to the new (Evince >= 49) namespace; _configure_dbus_names() overrides
# these once a bus connection is available.
EV_DAEMON_PATH = "/org/gnome/Evince/Daemon"
EV_DAEMON_NAME = "org.gnome.Evince.Daemon"
EV_DAEMON_IFACE = "org.gnome.Evince.Daemon"

EVINCE_PATH = "/org/gnome/Evince/Evince"
EVINCE_IFACE = "org.gnome.Evince.Application"

EV_WINDOW_IFACE = "org.gnome.Evince.Window"
EV_WINDOW_PATH = "/org/gnome/Evince/Window/0"


def startEvinceDaemon():
    bus = dbus.SessionBus()
    _configure_dbus_names(bus)
    daemon = bus.get_object(EV_DAEMON_NAME, EV_DAEMON_PATH, follow_name_owner_changes=True)
    return (bus, daemon)


class EvinceWindowProxy:
    """A DBUS proxy for an Evince Window."""

    daemon = None
    bus = None

    def __init__(self, uri, editor, logger):
        assert uri is not None
        assert editor is not None
        assert logger is not None
        self.logger = logger
        self.uri = uri
        self.editor = editor
        self.status = CLOSED
        self.dbus_name = ""
        self._handler = None
        try:
            if EvinceWindowProxy.daemon is None:
                (EvinceWindowProxy.bus, EvinceWindowProxy.daemon) = startEvinceDaemon()

            EvinceWindowProxy.bus.add_signal_receiver(
                self._on_doc_loaded,
                signal_name="DocumentLoaded",
                dbus_interface=EV_WINDOW_IFACE,
                sender_keyword="sender",
            )
            self._get_dbus_name(False)

        except dbus.DBusException:
            self.logger.debug("Could not connect to the Evince Daemon")

    def _on_doc_loaded(self, uri, **keyargs):
        if uri == self.uri and self._handler is None:
            self.handle_find_document_reply(keyargs["sender"])

    def _get_dbus_name(self, spawn):
        EvinceWindowProxy.daemon.FindDocument(
            self.uri,
            spawn,
            reply_handler=self.handle_find_document_reply,
            error_handler=self.handle_find_document_error,
            dbus_interface=EV_DAEMON_IFACE,
        )

    def handle_find_document_error(self, error):
        self.logger.debug("FindDocument DBus call has failed")

    def handle_find_document_reply(self, evince_name):
        if evince_name == "":
            self.logger.debug("Did not find an Evince with our document")
            return
        self.logger.debug("Found Evince with our document: %r", evince_name)
        if self._handler is not None:
            handler = self._handler
        else:
            handler = self.handle_get_window_list_reply
        self.dbus_name = evince_name
        self.status = RUNNING
        self.evince = EvinceWindowProxy.bus.get_object(self.dbus_name, EVINCE_PATH)
        self.evince.GetWindowList(
            dbus_interface=EVINCE_IFACE, reply_handler=handler, error_handler=self.handle_get_window_list_error
        )

    def handle_get_window_list_error(self, e):
        self.logger.debug("GetWindowList DBus call has failed")

    def handle_get_window_list_reply(self, window_list):
        if len(window_list) > 0:
            window_obj = EvinceWindowProxy.bus.get_object(self.dbus_name, window_list[0])
            self.window = dbus.Interface(window_obj, EV_WINDOW_IFACE)
            self.window.connect_to_signal("SyncSource", self.on_sync_source)
        else:
            self.logger.debug("GetWindowList returned empty list")

    def on_sync_source(self, input_file, source_link, timestamp):
        path = urllib.parse.unquote(input_file.split("file://")[1])
        line = source_link[0]
        self.logger.debug("Go to %s:%s", path, line)
        cmd = re.sub("%f", shlex.quote(path), self.editor)
        cmd = re.sub("%l", str(line), cmd)
        subprocess.call(cmd, shell=True)


def get_uri(file):
    path = os.path.abspath(file)
    return "file://%s" % (urllib.parse.quote(path, safe="%/:=&?~#+!$,;'@()*[]"))


def startEvince(line, tex_file, pdf_file, editor_command):
    logger = logging.getLogger("evince_synctex")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())

    import dbus.mainloop.glib
    from gi.repository import GLib

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    pdf_uri = get_uri(pdf_file)
    (bus, daemon) = startEvinceDaemon()

    already_opened = daemon.FindDocument(pdf_uri, False, dbus_interface=EV_DAEMON_IFACE)

    if line is not None:
        if tex_file is None:
            tex_file = os.path.splitext(pdf_file)[0] + ".tex"
        dbus_name = daemon.FindDocument(pdf_uri, True, dbus_interface=EV_DAEMON_IFACE)
        window = bus.get_object(dbus_name, EV_WINDOW_PATH)
        window.SyncView(tex_file, (line, 1), 0, dbus_interface=EV_WINDOW_IFACE)

    if already_opened:
        return

    process = subprocess.Popen(("evince", pdf_uri))

    def poll_viewer_process():
        process.poll()
        if process.returncode is not None:
            exit(0)
        return True

    try:
        EvinceWindowProxy.instance = EvinceWindowProxy(pdf_uri, editor_command, logger)
        GLib.idle_add(poll_viewer_process)
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass
    finally:
        process.terminate()
        process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__.lstrip())
    parser.add_argument(
        "-f",
        "--forward",
        type=int,
        dest="line",
        metavar="LINE",
        help="Performs a forward search with specified line number",
    )
    parser.add_argument(
        "-t",
        "--tex",
        dest="tex_file",
        metavar="TEX_FILE",
        help="The TeX source file to sync from on forward search (defaults to the PDF basename with a .tex extension)",
    )
    parser.add_argument("pdf_file", metavar="PDF_FILE", help="The PDF file to display")
    parser.add_argument("editor_command", metavar="EDITOR_COMMAND", help="The editor command to run on Ctrl+Click")
    startEvince(**vars(parser.parse_args()))


if __name__ == "__main__":
    main()
